"""System nodes: environment, processes, machine info, timers and events."""

from __future__ import annotations

import os
import platform
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from ...typesystem import DataType
from ..base import ParamSpec, inp, node, out


@node(
    "system.env_get",
    "Get Environment Variable",
    "System",
    inputs=[],
    outputs=[out("value", DataType.STRING), out("found", DataType.BOOLEAN)],
    params=[ParamSpec("name", "Variable", "text", "")],
    pure=False,
    codegen="python",
)
def env_get(ctx, inputs, params):
    name = str(params.get("name") or "")
    if not name:
        raise ValueError("environment variable name is empty")
    value = os.environ.get(name)
    return {"value": value or "", "found": value is not None}


@node(
    "system.env_set",
    "Set Environment Variable",
    "System",
    description="Sets an environment variable for the current SYNAPSE process.",
    inputs=[inp("value", DataType.STRING)],
    outputs=[out("value", DataType.STRING)],
    params=[ParamSpec("name", "Variable", "text", "")],
    pure=False,
)
def env_set(ctx, inputs, params):
    name = str(params.get("name") or "")
    if not name:
        raise ValueError("environment variable name is empty")
    value = "" if inputs.get("value") is None else str(inputs.get("value"))
    os.environ[name] = value
    return {"value": value}


@node(
    "system.process_run",
    "Run Process",
    "System",
    description="Runs a program and captures its output. Disabled unless the project allows processes.",
    inputs=[inp("args", DataType.ARRAY, None), inp("stdin", DataType.STRING, None)],
    outputs=[
        out("stdout", DataType.STRING),
        out("stderr", DataType.STRING),
        out("code", DataType.INTEGER),
        out("ok", DataType.BOOLEAN),
    ],
    params=[
        ParamSpec("command", "Command", "multiline", "python --version"),
        ParamSpec("cwd", "Working directory", "text", ""),
        ParamSpec("timeout", "Timeout (s)", "float", 30.0),
        ParamSpec("shell", "Run through shell", "bool", False),
    ],
    pure=False,
    blocking=True,
    keywords=("shell", "subprocess", "exec"),
)
async def process_run(ctx, inputs, params):
    ctx.security.check_process()
    command = str(params.get("command") or "").strip()
    if not command:
        raise ValueError("command is empty")
    extra = inputs.get("args")
    argv: list[str] = shlex.split(command)
    if isinstance(extra, list):
        argv.extend(str(a) for a in extra)
    cwd = str(params.get("cwd") or "") or None
    if cwd:
        cwd = ctx.security.resolve_path(cwd)
    timeout = float(params.get("timeout") or 30.0)
    stdin = inputs.get("stdin")
    use_shell = bool(params.get("shell"))

    def run() -> tuple[str, str, int]:
        completed = subprocess.run(
            command + (" " + " ".join(shlex.quote(a) for a in map(str, extra)) if isinstance(extra, list) else "")
            if use_shell
            else argv,
            cwd=cwd,
            input=None if stdin is None else str(stdin),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=use_shell,
            env=dict(os.environ),
        )
        return completed.stdout, completed.stderr, completed.returncode

    ctx.log(f"running: {command}", "info")
    try:
        stdout, stderr, code = await ctx.run_blocking(run)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"process did not finish within {timeout:g}s") from exc
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"program not found: {command.split()[0]}") from exc
    return {"stdout": stdout, "stderr": stderr, "code": code, "ok": code == 0}


@node(
    "system.info",
    "System Information",
    "System",
    outputs=[out("info", DataType.DICTIONARY), out("platform", DataType.STRING)],
    params=[],
    pure=False,
    codegen="python",
)
def system_info(ctx, inputs, params):
    info = {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cpu_count": os.cpu_count(),
        "cwd": os.getcwd(),
        "synapse_project": ctx.project_dir or "",
    }
    try:
        import shutil

        usage = shutil.disk_usage(ctx.project_dir or os.getcwd())
        info["disk_free"] = usage.free
        info["disk_total"] = usage.total
    except OSError:
        pass
    return {"info": info, "platform": info["platform"]}


@node(
    "system.timer",
    "Timer",
    "System",
    description="Waits for a number of seconds, then emits the elapsed time and timestamp.",
    inputs=[inp("seconds", DataType.ANY, None)],
    outputs=[
        out("seconds", DataType.FLOAT),
        out("timestamp", DataType.FLOAT),
        out("iso", DataType.STRING),
    ],
    params=[ParamSpec("delay", "Delay (s)", "float", 0.5, minimum=0.0, maximum=3600.0)],
    pure=False,
    keywords=("sleep", "delay", "wait", "clock"),
)
async def timer(ctx, inputs, params):
    delay = inputs.get("seconds")
    delay = float(params.get("delay") or 0.0) if delay is None else float(delay)
    if delay < 0:
        raise ValueError("delay cannot be negative")
    if delay > 3600:
        raise ValueError("delay cannot exceed one hour")
    await ctx.sleep(delay)
    now = time.time()
    return {
        "seconds": delay,
        "timestamp": now,
        "iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
    }


@node(
    "system.timestamp",
    "Timestamp",
    "System",
    outputs=[out("timestamp", DataType.FLOAT), out("iso", DataType.STRING), out("year", DataType.INTEGER)],
    params=[ParamSpec("utc", "UTC", "bool", True)],
    pure=False,
    codegen="python",
)
def timestamp(ctx, inputs, params):
    now = datetime.now(timezone.utc) if params.get("utc") else datetime.now()
    return {"timestamp": now.timestamp(), "iso": now.isoformat(), "year": now.year}


@node(
    "system.uuid",
    "UUID",
    "System",
    outputs=[out("value", DataType.STRING)],
    params=[ParamSpec("upper", "Uppercase", "bool", False), ParamSpec("hex", "No dashes", "bool", False)],
    pure=False,
    codegen="python",
)
def uuid_node(ctx, inputs, params):
    text = uuid.uuid4().hex if params.get("hex") else str(uuid.uuid4())
    return {"value": text.upper() if params.get("upper") else text}


@node(
    "system.emit_event",
    "Emit Event",
    "System",
    description="Publishes a named event that Event nodes in this run can wait for.",
    inputs=[inp("payload", DataType.ANY, None)],
    outputs=[out("payload", DataType.ANY)],
    params=[ParamSpec("name", "Event name", "text", "event")],
    pure=False,
)
async def emit_event(ctx, inputs, params):
    name = str(params.get("name") or "")
    if not name:
        raise ValueError("event name is empty")
    await ctx.emit_event(name, inputs.get("payload"))
    return {"payload": inputs.get("payload")}


@node(
    "system.wait_event",
    "Wait For Event",
    "System",
    inputs=[],
    outputs=[out("payload", DataType.ANY), out("received", DataType.BOOLEAN)],
    params=[
        ParamSpec("name", "Event name", "text", "event"),
        ParamSpec("timeout", "Timeout (s)", "float", 5.0, minimum=0.0),
    ],
    pure=False,
)
async def wait_event(ctx, inputs, params):
    name = str(params.get("name") or "")
    if not name:
        raise ValueError("event name is empty")
    timeout = float(params.get("timeout") or 5.0)
    try:
        payload = await ctx.wait_for_event(name, timeout if timeout > 0 else None)
    except TimeoutError:
        return {"payload": None, "received": False}
    return {"payload": payload, "received": True}


@node(
    "system.log_message",
    "Log Message",
    "System",
    description="Writes a formatted message to the console.",
    inputs=[inp("value", DataType.ANY, None)],
    outputs=[out("message", DataType.STRING)],
    params=[ParamSpec("message", "Message", "multiline", ""), ParamSpec("level", "Level", "choice", "info", choices=("info", "warning", "error", "debug"))],
    pure=False,
)
def log_message(ctx, inputs, params):
    text = str(params.get("message") or "")
    value = inputs.get("value")
    if value is not None:
        text = f"{text} {value}".strip() if text else str(value)
    ctx.log(text, str(params.get("level") or "info"))
    return {"message": text}
