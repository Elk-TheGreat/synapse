"""Script nodes: run Python (or a plugged-in language) inside a graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...scripting.runner import ScriptError, ScriptOptions, available_engines, run_script, validate_script
from ...typesystem import DataType
from ..base import ParamSpec, inp, node, out


def _options(ctx, params: dict, *, timeout: float | None = None) -> ScriptOptions:
    ctx.security.check_scripts()
    raw = str(params.get("allowed_imports") or "")
    extra = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    allowed = tuple(dict.fromkeys(tuple(ctx.security.script_allowed_imports) + tuple(extra)))
    return ScriptOptions(
        timeout=float(timeout if timeout is not None else params.get("timeout") or ctx.security.script_timeout),
        allowed_imports=allowed,
        allow_all_imports=bool(params.get("allow_all_imports")),
        working_dir=ctx.project_dir or None,
    )


@node(
    "script.python",
    "Python Script",
    "Scripting",
    description=(
        "Runs Python in an isolated interpreter. Use inputs['name'] for graph data and "
        "set result (or the outputs dict) to return values."
    ),
    inputs=[
        inp("inputs", DataType.DICTIONARY, None),
        inp("params", DataType.DICTIONARY, {}),
    ],
    outputs=[
        out("result", DataType.ANY),
        out("stdout", DataType.STRING),
        out("duration", DataType.FLOAT),
    ],
    params=[
        ParamSpec("engine", "Engine", "choice", "python", choices=("python",), description="Script language runtime"),
        ParamSpec(
            "code",
            "Code",
            "code",
            "total = sum(inputs.get('values', []))\nresult = {'total': total, 'count': len(inputs.get('values', []))}",
        ),
        ParamSpec("timeout", "Timeout (s)", "float", 10.0, minimum=0.5, maximum=300.0),
        ParamSpec("allowed_imports", "Extra allowed imports", "text", "", description="Comma separated module names"),
        ParamSpec("allow_all_imports", "Allow all imports", "bool", False, description="Disables the import allow-list"),
    ],
    pure=False,
    keywords=("python", "code", "script", "exec"),
)
async def python_script(ctx, inputs, params):
    code = str(params.get("code") or "")
    engine = str(params.get("engine") or "python")
    if engine not in available_engines():
        raise ValueError(f"script engine '{engine}' is not installed (available: {', '.join(available_engines())})")
    try:
        validate_script(code)
    except ScriptError as exc:
        raise ValueError(str(exc)) from exc
    options = _options(ctx, params)
    try:
        outcome = await ctx.run_blocking(
            run_script,
            code,
            dict(inputs.get("inputs") or {}),
            dict(inputs.get("params") or {}),
            engine=engine,
            options=options,
        )
    except ScriptError as exc:
        raise RuntimeError(str(exc)) from exc
    if outcome.stdout:
        ctx.log(outcome.stdout.rstrip(), "debug")
    return {"result": outcome.result, "stdout": outcome.stdout, "duration": outcome.duration}


@node(
    "script.python_file",
    "Python Script File",
    "Scripting",
    description="Runs a .py file from the project folder in the isolated interpreter.",
    inputs=[inp("inputs", DataType.DICTIONARY, None), inp("params", DataType.DICTIONARY, None)],
    outputs=[out("result", DataType.ANY), out("stdout", DataType.STRING), out("duration", DataType.FLOAT)],
    params=[
        ParamSpec("path", "Script path", "file", "scripts/main.py"),
        ParamSpec("timeout", "Timeout (s)", "float", 10.0, minimum=0.5, maximum=300.0),
        ParamSpec("allowed_imports", "Extra allowed imports", "text", ""),
        ParamSpec("allow_all_imports", "Allow all imports", "bool", False),
    ],
    pure=False,
    blocking=True,
)
async def python_script_file(ctx, inputs, params):
    path = ctx.security.resolve_path(str(params.get("path") or ""))
    if not Path(path).is_file():
        raise FileNotFoundError(f"script file not found: {path}")
    if Path(path).suffix.lower() != ".py":
        raise ValueError("Python Script File only runs .py files")
    code = await ctx.run_blocking(Path(path).read_text, "utf-8")
    try:
        validate_script(code, str(path))
    except ScriptError as exc:
        raise ValueError(str(exc)) from exc
    options = _options(ctx, params)
    try:
        outcome = await ctx.run_blocking(
            run_script,
            code,
            dict(inputs.get("inputs") or {}),
            dict(inputs.get("params") or {}),
            options=options,
        )
    except ScriptError as exc:
        raise RuntimeError(str(exc)) from exc
    if outcome.stdout:
        ctx.log(outcome.stdout.rstrip(), "debug")
    return {"result": outcome.result, "stdout": outcome.stdout, "duration": outcome.duration}
