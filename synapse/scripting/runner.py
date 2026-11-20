"""Untrusted script execution.

User scripts run in a separate, isolated Python interpreter (``python -I``)
with a timeout, a restricted import allow-list and no inherited SYNAPSE state.
That gives crash and hang isolation; it is not an OS sandbox (a determined
script can still use the interpreter), which is documented in
``documentation/SECURITY.md``.  Imported scripts are never executed until a
node explicitly runs them.

Other languages plug in through :func:`register_engine`: an engine is any
object with ``run(source, inputs, params, options) -> ScriptResult``.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class ScriptError(RuntimeError):
    """Raised when a script fails, times out or returns invalid output."""


@dataclass
class ScriptOptions:
    timeout: float = 10.0
    allowed_imports: tuple[str, ...] = ()
    allow_all_imports: bool = False
    working_dir: str | None = None


@dataclass
class ScriptResult:
    result: Any = None
    stdout: str = ""
    duration: float = 0.0
    engine: str = "python"


# The worker is a self-contained program: it reads one JSON payload from stdin
# and prints one JSON response.  Keeping it inline avoids shipping an extra
# file that a user could accidentally edit.
_WORKER = r'''
import builtins, contextlib, io, json, sys, time, traceback

payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
source = payload["source"]
inputs = payload["inputs"]
params = payload["params"]
allowed = set(payload["allowed_imports"])
allow_all = payload["allow_all"]

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if not allow_all and root not in allowed:
        raise ImportError(
            "import of '" + name + "' is not allowed; add it to the script "
            "node's allowed imports (or enable all imports)"
        )
    return real_import(name, globals, locals, fromlist, level)

safe = {}
for key, value in vars(builtins).items():
    if key in ("__import__", "open", "exec", "eval", "compile", "input", "breakpoint", "help", "exit", "quit"):
        continue
    safe[key] = value
safe["__import__"] = guarded_import
safe["__build_class__"] = builtins.__build_class__
safe["print"] = print

namespace = {
    "__name__": "synapse_script",
    "__doc__": "SYNAPSE script node",
    "__builtins__": safe,
    "inputs": inputs,
    "params": params,
    "outputs": {},
}

buffer = io.StringIO()
started = time.perf_counter()
try:
    code = compile(source, "<synapse script>", "exec")
    with contextlib.redirect_stdout(buffer):
        exec(code, namespace)
    result = namespace.get("result")
    if result is None and namespace.get("outputs"):
        result = namespace["outputs"]
    response = {
        "ok": True,
        "result": result,
        "stdout": buffer.getvalue(),
        "duration": time.perf_counter() - started,
    }
except BaseException as exc:
    frames = traceback.format_exception(type(exc), exc, exc.__traceback__)
    user_frames = [line for line in frames if "synapse script" in line or "<synapse script>" in line]
    response = {
        "ok": False,
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": "".join(frames[-6:]),
        "stdout": buffer.getvalue(),
        "duration": time.perf_counter() - started,
    }

try:
    sys.stdout.write(json.dumps(response, default=str))
except TypeError as exc:
    sys.stdout.write(json.dumps({
        "ok": False,
        "error": "script result cannot be converted to JSON: " + str(exc),
        "traceback": "",
        "stdout": buffer.getvalue(),
        "duration": time.perf_counter() - started,
    }))
'''


class ScriptEngine(Protocol):
    name: str

    def run(self, source: str, inputs: dict, params: dict, options: ScriptOptions) -> ScriptResult:
        ...


class PythonEngine:
    name = "python"

    def run(self, source: str, inputs: dict, params: dict, options: ScriptOptions) -> ScriptResult:
        if not source.strip():
            raise ScriptError("script is empty")
        payload = json.dumps(
            {
                "source": source,
                "inputs": _encode(inputs),
                "params": _encode(params),
                "allowed_imports": list(options.allowed_imports),
                "allow_all": bool(options.allow_all_imports),
            }
        ).encode("utf-8")
        command = [sys.executable, "-I", "-c", _WORKER]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                timeout=max(0.5, float(options.timeout)),
                cwd=options.working_dir or None,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScriptError(
                f"script exceeded its {options.timeout:g}s time limit and was stopped"
            ) from exc
        duration = time.perf_counter() - started
        if completed.returncode != 0 and not completed.stdout:
            raise ScriptError(
                "script interpreter failed: "
                + completed.stderr.decode("utf-8", "replace").strip()[:500]
            )
        try:
            response = json.loads(completed.stdout.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ScriptError(
                "script produced no valid response: "
                + completed.stderr.decode("utf-8", "replace").strip()[:400]
            ) from exc
        if not response.get("ok"):
            message = response.get("error") or "script failed"
            trace = response.get("traceback") or ""
            raise ScriptError(message + ("\n" + trace if trace else ""))
        return ScriptResult(
            result=_decode(response.get("result")),
            stdout=response.get("stdout") or "",
            duration=duration,
        )


_ENGINES: dict[str, ScriptEngine] = {"python": PythonEngine()}


def register_engine(engine: ScriptEngine) -> None:
    """Plug in another language runtime (JavaScript, Rust, ...)."""
    _ENGINES[engine.name] = engine


def unregister_engine(name: str) -> None:
    _ENGINES.pop(name, None)


def available_engines() -> list[str]:
    return sorted(_ENGINES)


def get_engine(name: str) -> ScriptEngine:
    engine = _ENGINES.get(name)
    if engine is None:
        raise ScriptError(
            f"no script engine named '{name}' is installed (available: {', '.join(available_engines())})"
        )
    return engine


def validate_script(source: str, filename: str = "<synapse script>") -> None:
    """Compile only - used by the editor before running."""
    try:
        compile(source, filename, "exec")
    except SyntaxError as exc:
        raise ScriptError(f"SyntaxError: {exc.msg} (line {exc.lineno})") from exc


def run_script(
    source: str,
    inputs: dict | None = None,
    params: dict | None = None,
    *,
    engine: str = "python",
    options: ScriptOptions | None = None,
) -> ScriptResult:
    return get_engine(engine).run(
        source,
        dict(inputs or {}),
        dict(params or {}),
        options or ScriptOptions(),
    )


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (set, frozenset)):
        return [_encode(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__bytes__"}:
            return base64.b64decode(str(value["__bytes__"]))
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value
