"""File system nodes.

All paths are resolved by the run's :class:`SecurityPolicy`: relative paths are
joined to the project folder and nothing outside the allowed roots is touched.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ...typesystem import DataType, FileRef
from ..base import ParamSpec, inp, node, out


def _path(ctx, value: Any, *, write: bool = False) -> str:
    if isinstance(value, FileRef):
        value = str(value.path)
    if value is None or str(value).strip() == "":
        raise ValueError("a file path is required")
    return ctx.security.resolve_path(str(value), write=write)


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


@node(
    "files.read",
    "Read File",
    "Files",
    description="Reads a file as text or bytes (inside the project folder).",
    inputs=[inp("path", DataType.ANY)],
    outputs=[out("text", DataType.STRING), out("data", DataType.BYTES), out("size", DataType.INTEGER)],
    params=[
        ParamSpec("encoding", "Encoding", "text", "utf-8"),
        ParamSpec("binary", "Read as bytes", "bool", False),
        ParamSpec("max_bytes", "Max bytes", "int", 0, minimum=0, description="0 uses the project limit."),
    ],
    pure=False,
    blocking=True,
    keywords=("load", "open"),
)
async def read_file(ctx, inputs, params):
    path = _path(ctx, inputs.get("path"))
    limit = int(params.get("max_bytes") or 0) or ctx.security.max_file_bytes
    size = await ctx.run_blocking(_size, path)
    if size > limit:
        raise ValueError(f"file is {size} bytes, above the limit of {limit} bytes")
    raw = await ctx.run_blocking(Path(path).read_bytes)
    if params.get("binary"):
        return {"text": "", "data": raw, "size": len(raw)}
    try:
        text = raw.decode(str(params.get("encoding") or "utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"file is not valid {params.get('encoding') or 'utf-8'} text: {exc}") from exc
    return {"text": text, "data": raw, "size": len(raw)}


@node(
    "files.write",
    "Write File",
    "Files",
    description="Writes text or bytes to a file, creating folders as needed.",
    inputs=[inp("path", DataType.ANY), inp("content", DataType.ANY)],
    outputs=[out("path", DataType.ANY), out("size", DataType.INTEGER)],
    params=[
        ParamSpec("encoding", "Encoding", "text", "utf-8"),
        ParamSpec("append", "Append", "bool", False),
    ],
    pure=False,
    blocking=True,
    keywords=("save", "store"),
)
async def write_file(ctx, inputs, params):
    path = _path(ctx, inputs.get("path"), write=True)
    content = inputs.get("content")
    if isinstance(content, str):
        raw = content.encode(str(params.get("encoding") or "utf-8"))
    elif isinstance(content, (bytes, bytearray)):
        raw = bytes(content)
    else:
        raw = str("" if content is None else content).encode("utf-8")
    mode = "ab" if params.get("append") else "wb"

    def write() -> int:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode) as handle:
            handle.write(raw)
        return len(raw)

    size = await ctx.run_blocking(write)
    ctx.log(f"wrote {size} bytes to {path}", "info")
    return {"path": FileRef(path), "size": size}


@node(
    "files.copy",
    "Copy File",
    "Files",
    inputs=[inp("source", DataType.ANY), inp("destination", DataType.ANY)],
    outputs=[out("path", DataType.ANY)],
    params=[ParamSpec("overwrite", "Overwrite", "bool", False)],
    pure=False,
    blocking=True,
)
async def copy_file(ctx, inputs, params):
    source = _path(ctx, inputs.get("source"))
    destination = _path(ctx, inputs.get("destination"), write=True)

    def copy() -> str:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        if os.path.isdir(source):
            shutil.copytree(source, destination, dirs_exist_ok=bool(params.get("overwrite")))
        else:
            if os.path.exists(destination) and not params.get("overwrite"):
                raise FileExistsError(f"'{destination}' already exists")
            shutil.copy2(source, destination)
        return destination

    return {"path": FileRef(await ctx.run_blocking(copy))}


@node(
    "files.move",
    "Move File",
    "Files",
    inputs=[inp("source", DataType.ANY), inp("destination", DataType.ANY)],
    outputs=[out("path", DataType.ANY)],
    params=[ParamSpec("overwrite", "Overwrite", "bool", False)],
    pure=False,
    blocking=True,
)
async def move_file(ctx, inputs, params):
    source = _path(ctx, inputs.get("source"), write=True)
    destination = _path(ctx, inputs.get("destination"), write=True)

    def move() -> str:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        if os.path.exists(destination) and not params.get("overwrite"):
            raise FileExistsError(f"'{destination}' already exists")
        return shutil.move(source, destination)

    return {"path": FileRef(await ctx.run_blocking(move))}


@node(
    "files.delete",
    "Delete File",
    "Files",
    description="Deletes a file, or an empty directory (set 'recursive' for a whole tree).",
    inputs=[inp("path", DataType.ANY)],
    outputs=[out("deleted", DataType.BOOLEAN)],
    params=[ParamSpec("recursive", "Recursive", "bool", False)],
    pure=False,
    blocking=True,
)
async def delete_file(ctx, inputs, params):
    path = _path(ctx, inputs.get("path"), write=True)

    def delete() -> bool:
        if os.path.isdir(path):
            if params.get("recursive"):
                shutil.rmtree(path)
            else:
                os.rmdir(path)
        else:
            os.remove(path)
        return True

    try:
        return {"deleted": await ctx.run_blocking(delete)}
    except FileNotFoundError:
        return {"deleted": False}


@node(
    "files.list",
    "List Directory",
    "Files",
    inputs=[inp("path", DataType.ANY, ".")],
    outputs=[
        out("files", DataType.ARRAY),
        out("names", DataType.ARRAY),
        out("count", DataType.INTEGER),
    ],
    params=[
        ParamSpec("pattern", "Glob pattern", "text", "*"),
        ParamSpec("recursive", "Recursive", "bool", False),
        ParamSpec("directories", "Include folders", "bool", False),
    ],
    pure=False,
    blocking=True,
    keywords=("ls", "folder", "directory"),
)
async def list_directory(ctx, inputs, params):
    root = _path(ctx, inputs.get("path") or ".")
    pattern = str(params.get("pattern") or "*")
    recursive = bool(params.get("recursive"))
    want_dirs = bool(params.get("directories"))

    def list_dir() -> list[str]:
        base = Path(root)
        if not base.exists():
            raise FileNotFoundError(f"'{root}' does not exist")
        if not base.is_dir():
            raise NotADirectoryError(f"'{root}' is not a directory")
        paths = base.rglob(pattern) if recursive else base.glob(pattern)
        found = [
            str(p)
            for p in sorted(paths)
            if (p.is_dir() if want_dirs else p.is_file())
        ]
        return found

    paths = await ctx.run_blocking(list_dir)
    return {
        "files": [FileRef(p) for p in paths],
        "names": [Path(p).name for p in paths],
        "count": len(paths),
    }


@node(
    "files.mkdir",
    "Create Directory",
    "Files",
    inputs=[inp("path", DataType.ANY)],
    outputs=[out("path", DataType.ANY)],
    params=[ParamSpec("parents", "Create parents", "bool", True)],
    pure=False,
    blocking=True,
)
async def create_directory(ctx, inputs, params):
    path = _path(ctx, inputs.get("path"), write=True)

    def make() -> str:
        Path(path).mkdir(parents=bool(params.get("parents")), exist_ok=True)
        return path

    return {"path": FileRef(await ctx.run_blocking(make))}


@node(
    "files.exists",
    "Path Exists",
    "Files",
    inputs=[inp("path", DataType.ANY)],
    outputs=[out("exists", DataType.BOOLEAN), out("is_file", DataType.BOOLEAN), out("is_dir", DataType.BOOLEAN)],
    pure=False,
    blocking=True,
)
async def path_exists(ctx, inputs, params):
    path = _path(ctx, inputs.get("path"))
    is_file = await ctx.run_blocking(os.path.isfile, path)
    is_dir = await ctx.run_blocking(os.path.isdir, path)
    return {"exists": is_file or is_dir, "is_file": is_file, "is_dir": is_dir}


@node(
    "files.info",
    "Path Info",
    "Files",
    inputs=[inp("path", DataType.ANY)],
    outputs=[out("info", DataType.DICTIONARY)],
    pure=False,
    blocking=True,
)
async def path_info(ctx, inputs, params):
    path = _path(ctx, inputs.get("path"))

    def info() -> dict:
        stat = os.stat(path)
        item = Path(path)
        return {
            "path": path,
            "name": item.name,
            "suffix": item.suffix,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "is_file": item.is_file(),
            "is_dir": item.is_dir(),
        }

    try:
        return {"info": await ctx.run_blocking(info)}
    except FileNotFoundError:
        return {"info": {"path": path, "exists": False}}
