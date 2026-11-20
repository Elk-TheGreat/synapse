"""Core graph plumbing: inputs, outputs, variables, constants, logging."""

from __future__ import annotations

import json
from typing import Any

from ...typesystem import DataType
from ..base import ParamSpec, inp, node, out


def _coerce_to_kind(value: Any, kind: str) -> Any:
    if value is None:
        return None
    if kind == "integer":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind == "string":
        return value if isinstance(value, str) else str(value)
    if kind == "json":

        if isinstance(value, str):
            return json.loads(value)
        return value
    return value


@node(
    "core.graph_input",
    "Graph Input",
    "Core",
    description="Reads a named input supplied when the graph or function runs.",
    inputs=[],
    outputs=[out("value", DataType.ANY)],
    params=[
        ParamSpec("name", "Input name", "text", "input"),
        ParamSpec(
            "variable_type",
            "Declared type",
            "choice",
            "any",
            choices=[t.value for t in DataType],
            description="Documentation type of this input; values are runtime checked.",
        ),
    ],
    pure=False,
    codegen="unsupported",
)
def graph_input(ctx, inputs, params):
    name = str(params.get("name") or "input")
    value = ctx._run.graph_inputs.get(name)
    if value is None and name in ctx.variables:
        value = ctx.variables[name]
    return {"value": value}


@node(
    "core.graph_output",
    "Graph Output",
    "Core",
    description="Publishes a named result of the graph or function.",
    inputs=[inp("value", DataType.ANY)],
    outputs=[],
    params=[ParamSpec("name", "Output name", "text", "result")],
    pure=False,
    codegen="unsupported",
)
def graph_output(ctx, inputs, params):
    return {}


@node(
    "core.constant",
    "Constant",
    "Core",
    description="Emits a typed constant value.",
    inputs=[],
    outputs=[out("value", DataType.ANY)],
    params=[
        ParamSpec(
            "value_type",
            "Type",
            "choice",
            "auto",
            choices=["auto"] + [t.value for t in DataType if t is not DataType.ANY],
        ),
        ParamSpec("value", "Value", "text", ""),
    ],
    codegen="python",
)
def constant(ctx, inputs, params):
    kind = str(params.get("value_type") or "auto")
    raw = params.get("value")
    if kind == "auto":
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
        else:
            value = raw
    elif kind == "json":
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise ValueError(f"constant is not valid JSON: {exc}") from exc
    else:
        try:
            value = _coerce_to_kind(raw, kind)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"constant value {raw!r} is not a valid {kind}: {exc}") from exc
    return {"value": value}


@node(
    "core.variable_get",
    "Get Variable",
    "Core",
    description="Reads a graph-scoped variable (shared by every node in the run).",
    inputs=[],
    outputs=[out("value", DataType.ANY)],
    params=[ParamSpec("name", "Variable", "text", "value")],
    pure=False,
    codegen="unsupported",
)
def variable_get(ctx, inputs, params):
    name = str(params.get("name") or "")
    if not name:
        raise ValueError("variable name is empty")
    if name not in ctx.variables:
        raise KeyError(f"variable '{name}' is not set in this graph")
    return {"value": ctx.variables[name]}


@node(
    "core.variable_set",
    "Set Variable",
    "Core",
    description="Assigns a graph-scoped variable and passes the value through.",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("value", DataType.ANY)],
    params=[ParamSpec("name", "Variable", "text", "value")],
    pure=False,
    codegen="unsupported",
)
def variable_set(ctx, inputs, params):
    name = str(params.get("name") or "")
    if not name:
        raise ValueError("variable name is empty")
    ctx.variables[name] = inputs.get("value")
    return {"value": inputs.get("value")}


@node(
    "core.log",
    "Log",
    "Core",
    description="Writes a message to the execution console and passes the value on.",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("value", DataType.ANY)],
    params=[ParamSpec("label", "Label", "text", "log"), ParamSpec("level", "Level", "choice", "info", choices=("info", "warning", "error", "debug"))],
    pure=False,
)
def log_node(ctx, inputs, params):
    from ...debugger.values import value_preview

    label = params.get("label") or "log"
    ctx.log(f"{label}: {value_preview(inputs.get('value'))}", str(params.get("level") or "info"))
    return {"value": inputs.get("value")}


@node(
    "core.assert",
    "Assert",
    "Core",
    description="Fails the run when a condition is false; otherwise passes the value through.",
    inputs=[inp("condition", DataType.BOOLEAN), inp("value", DataType.ANY)],
    outputs=[out("value", DataType.ANY)],
    params=[ParamSpec("message", "Failure message", "text", "assertion failed")],
    codegen="unsupported",
)
def assert_node(ctx, inputs, params):
    if not inputs.get("condition"):
        raise AssertionError(str(params.get("message") or "assertion failed"))
    return {"value": inputs.get("value")}
