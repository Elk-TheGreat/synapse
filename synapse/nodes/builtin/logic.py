"""Logic and control flow nodes.

SYNAPSE is a dataflow language: `If` selects between two values instead of
containing branches, and repetition is expressed by calling a reusable
function for each item.  Loop bodies can signal ``Break`` or ``Continue``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...typesystem import DataType
from ..base import ParamSpec, inp, node, out


@dataclass
class ControlSignal:
    """Returned by Break/Continue nodes inside a loop body function."""

    kind: str  # break | continue
    value: Any = None

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{self.kind}>"


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "no", "off", "null", "none")
    return bool(value)


@node(
    "logic.if",
    "If",
    "Logic",
    description="Chooses between two values based on a condition.",
    inputs=[
        inp("condition", DataType.BOOLEAN),
        inp("true_value", DataType.ANY),
        inp("false_value", DataType.ANY),
    ],
    outputs=[out("result", DataType.ANY)],
    keywords=("conditional", "branch", "ternary"),
    codegen="python",
)
def if_node(ctx, inputs, params):
    return {"result": inputs["true_value"] if _as_bool(inputs["condition"]) else inputs["false_value"]}


@node(
    "logic.else",
    "Else",
    "Logic",
    description="Chooses a value when the condition is false (inverse of If).",
    inputs=[
        inp("condition", DataType.BOOLEAN),
        inp("false_value", DataType.ANY),
        inp("true_value", DataType.ANY),
    ],
    outputs=[out("result", DataType.ANY)],
    codegen="python",
)
def else_node(ctx, inputs, params):
    return {"result": inputs["false_value"] if _as_bool(inputs["condition"]) else inputs["true_value"]}


@node(
    "logic.switch",
    "Switch",
    "Logic",
    description="Selects one of four values by comparing the selector against configured cases.",
    inputs=[
        inp("selector", DataType.ANY),
        inp("case_0", DataType.ANY, None),
        inp("case_1", DataType.ANY, None),
        inp("case_2", DataType.ANY, None),
        inp("case_3", DataType.ANY, None),
        inp("default", DataType.ANY, None),
    ],
    outputs=[out("result", DataType.ANY), out("matched_index", DataType.INTEGER)],
    params=[
        ParamSpec(
            "cases",
            "Cases (comma separated)",
            "text",
            "a,b,c,d",
            description="Value compared to the selector for case_0..case_3.",
        )
    ],
    codegen="python",
)
def switch_node(ctx, inputs, params):
    cases = [c.strip() for c in str(params.get("cases") or "").split(",")]
    selector = inputs.get("selector")
    key = "" if selector is None else str(selector)
    for index in range(4):
        expected = cases[index] if index < len(cases) else ""
        if key == expected:
            return {"result": inputs.get(f"case_{index}"), "matched_index": index}
    return {"result": inputs.get("default"), "matched_index": -1}


def _bool_node(type_id: str, name: str, op: str):
    @node(
        type_id,
        name,
        "Logic",
        description=f"Boolean {name.lower()} of its inputs.",
        inputs=[
            inp("a", DataType.BOOLEAN),
            inp("b", DataType.BOOLEAN, False),
            inp("c", DataType.BOOLEAN, False),
        ],
        outputs=[out("result", DataType.BOOLEAN)],
        codegen="python",
    )
    def logic_op(ctx, inputs, params, _op=op):
        values = [_as_bool(inputs.get(k)) for k in ("a", "b", "c")]
        return {"result": all(values) if _op == "and" else any(values)}

    return logic_op


and_node = _bool_node("logic.and", "AND", "and")
or_node = _bool_node("logic.or", "OR", "or")


@node(
    "logic.not",
    "NOT",
    "Logic",
    description="Inverts a boolean value.",
    inputs=[inp("value", DataType.BOOLEAN)],
    outputs=[out("result", DataType.BOOLEAN)],
    keywords=("negate", "invert"),
    codegen="python",
)
def not_node(ctx, inputs, params):
    return {"result": not _as_bool(inputs.get("value"))}


COMPARATORS = ("==", "!=", "<", "<=", ">", ">=", "contains", "starts with", "ends with", "is null")


@node(
    "logic.compare",
    "Compare",
    "Logic",
    description="Compares two values and returns a boolean.",
    inputs=[inp("a", DataType.ANY), inp("b", DataType.ANY)],
    outputs=[out("result", DataType.BOOLEAN)],
    params=[ParamSpec("operator", "Operator", "choice", "==", choices=COMPARATORS)],
    keywords=("equal", "greater", "less"),
    codegen="python",
)
def compare(ctx, inputs, params):
    op = str(params.get("operator") or "==")
    a, b = inputs.get("a"), inputs.get("b")
    if op == "is null":
        return {"result": a is None}
    if op in ("contains", "starts with", "ends with"):
        text = "" if a is None else str(a)
        needle = "" if b is None else str(b)
        if op == "contains":
            return {"result": needle in text}
        if op == "starts with":
            return {"result": text.startswith(needle)}
        return {"result": text.endswith(needle)}
    if op == "==":
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            return {"result": a == b}
        return {"result": a == b or (a is not None and b is not None and str(a) == str(b))}
    if op == "!=":
        return {"result": not compare(ctx, inputs, {"operator": "=="})["result"]}
    if a is None or b is None:
        return {"result": False}
    try:
        if op == "<":
            return {"result": a < b}
        if op == "<=":
            return {"result": a <= b}
        if op == ">":
            return {"result": a > b}
        if op == ">=":
            return {"result": a >= b}
    except TypeError:
        left, right = str(a), str(b)
        return {"result": {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]}
    raise ValueError(f"unsupported comparator '{op}'")


@node(
    "logic.break",
    "Break",
    "Logic",
    description="Stops the enclosing loop. Connect the 'signal' output to the loop body function's result.",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("signal", DataType.ANY), out("value", DataType.ANY)],
    pure=False,
)
def break_node(ctx, inputs, params):
    return {"signal": ControlSignal("break", inputs.get("value")), "value": inputs.get("value")}


@node(
    "logic.continue",
    "Continue",
    "Logic",
    description="Skips to the next iteration of the enclosing loop.",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("signal", DataType.ANY), out("value", DataType.ANY)],
    pure=False,
)
def continue_node(ctx, inputs, params):
    return {"signal": ControlSignal("continue", inputs.get("value")), "value": inputs.get("value")}


def _extract_signal(result: dict) -> ControlSignal | None:
    for key in ("signal", "result"):
        value = result.get(key)
        if isinstance(value, ControlSignal):
            return value
    for value in result.values():
        if isinstance(value, ControlSignal):
            return value
    return None


def _primary(result: dict) -> Any:
    if "result" in result:
        return result["result"]
    if "value" in result:
        return result["value"]
    for key, value in result.items():
        if key != "accumulator":
            return value
    return None


def _pick(result: dict, name: str) -> Any:
    if name in result:
        return result[name]
    return None


@node(
    "logic.for_loop",
    "For Loop",
    "Logic",
    description=(
        "Calls a body function once per item. The body receives item, index and "
        "accumulator, and may return result/accumulator or a Break/Continue signal."
    ),
    inputs=[
        inp("items", DataType.ARRAY),
        inp("initial_accumulator", DataType.ANY),
    ],
    outputs=[
        out("results", DataType.ARRAY),
        out("accumulator", DataType.ANY),
        out("iterations", DataType.INTEGER),
    ],
    params=[
        ParamSpec("body", "Body function", "function", ""),
        ParamSpec("max_iterations", "Max iterations", "int", 10000, minimum=1),
    ],
    pure=False,
    keywords=("foreach", "iterate", "map"),
)
async def for_loop(ctx, inputs, params):
    items = inputs.get("items")
    if items is None:
        raise ValueError("'items' input is empty")
    if not isinstance(items, (list, tuple)):
        items = [items]
    body = ctx.resolve_function(str(params.get("body") or ""))
    if body is None:
        raise ValueError("For Loop needs a body function (select one in the inspector)")
    limit = min(int(params.get("max_iterations") or 10000), ctx._run.options.max_loop_iterations)
    if len(items) > limit:
        raise ValueError(f"array has {len(items)} items, above the limit of {limit}")
    accumulator = inputs.get("initial_accumulator")
    results: list[Any] = []
    iterations = 0
    for index, item in enumerate(items):
        ctx.check_cancelled()
        call = {"item": item, "index": index, "accumulator": accumulator}
        try:
            out_values = await ctx.call_function(body.id, call)
        except Exception as exc:
            raise RuntimeError(f"loop body failed at index {index}: {exc}") from exc
        iterations += 1
        signal = _extract_signal(out_values)
        if "accumulator" in out_values:
            accumulator = out_values["accumulator"]
        if signal is not None and signal.kind == "break":
            break
        if signal is not None and signal.kind == "continue":
            continue
        results.append(_primary(out_values))
    return {"results": results, "accumulator": accumulator, "iterations": iterations}


@node(
    "logic.while_loop",
    "While Loop",
    "Logic",
    description=(
        "Repeats a body function while a condition function returns true. Both "
        "functions receive the current state and the body returns the next state."
    ),
    inputs=[inp("initial_state", DataType.ANY)],
    outputs=[
        out("state", DataType.ANY),
        out("iterations", DataType.INTEGER),
        out("exhausted", DataType.BOOLEAN),
    ],
    params=[
        ParamSpec("condition", "Condition function", "function", ""),
        ParamSpec("body", "Body function", "function", ""),
        ParamSpec("max_iterations", "Max iterations", "int", 1000, minimum=1),
    ],
    pure=False,
    keywords=("loop", "repeat"),
)
async def while_loop(ctx, inputs, params):
    condition = ctx.resolve_function(str(params.get("condition") or ""))
    body = ctx.resolve_function(str(params.get("body") or ""))
    if condition is None:
        raise ValueError("While Loop needs a condition function")
    if body is None:
        raise ValueError("While Loop needs a body function")
    limit = min(int(params.get("max_iterations") or 1000), ctx._run.options.max_loop_iterations)
    state = inputs.get("initial_state")
    iterations = 0
    while True:
        ctx.check_cancelled()
        cond_values = await ctx.call_function(condition.id, {"state": state, "iterations": iterations})
        cond = cond_values.get("condition", cond_values.get("result", _primary(cond_values)))
        if not _as_bool(cond):
            return {"state": state, "iterations": iterations, "exhausted": False}
        if iterations >= limit:
            return {"state": state, "iterations": iterations, "exhausted": True}
        body_values = await ctx.call_function(
            body.id, {"state": state, "iterations": iterations}
        )
        signal = _extract_signal(body_values)
        if signal is not None and signal.kind == "break":
            return {"state": state, "iterations": iterations, "exhausted": False}
        iterations += 1
        new_state = _pick(body_values, "state")
        if new_state is None:
            new_state = _pick(body_values, "result")
        if signal is not None and signal.kind == "continue":
            continue
        state = new_state


@node(
    "logic.cast",
    "Cast",
    "Logic",
    description="Explicitly converts a value to another type (fails when lossy or invalid).",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("value", DataType.ANY)],
    params=[
        ParamSpec(
            "target",
            "Target type",
            "choice",
            "string",
            choices=["boolean", "integer", "float", "string", "bytes", "array", "dictionary", "json"],
        )
    ],
    codegen="python",
)
def cast(ctx, inputs, params):
    from ...typesystem import coerce_value

    target = str(params.get("target") or "string")
    value = inputs.get("value")
    if target == "json":
        import json

        if isinstance(value, str):
            return {"value": json.loads(value)}
        return {"value": value}
    return {"value": coerce_value(value, DataType(target), port="value")}
