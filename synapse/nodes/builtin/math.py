"""Mathematics nodes.

Arithmetic ports accept any numeric value (numbers or numeric strings) and are
declared as ``any`` so integer and float graphs can be wired freely without
silent precision loss; the nodes fail loudly on non-numeric input.
"""

from __future__ import annotations

import math
import random
from typing import Any

from ...typesystem import DataType
from ..base import ParamSpec, inp, node, out


def _num(value: Any, label: str) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{label} is not a number: {value!r}") from exc
    raise ValueError(f"{label} is not a number: {value!r}")


def _number_out(value: float | int) -> Any:
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    return value


def _binary(type_id, name, symbol, fn, *, description="", params=()):
    @node(
        type_id,
        name,
        "Mathematics",
        description=description or f"Computes a {symbol} b.",
        inputs=[inp("a", DataType.ANY), inp("b", DataType.ANY)],
        outputs=[out("result", DataType.ANY)],
        params=list(params),
        keywords=(symbol, "arithmetic"),
        codegen="python",
    )
    def operation(ctx, inputs, p, _fn=fn, _symbol=symbol):
        a = _num(inputs.get("a"), "a")
        b = _num(inputs.get("b"), "b")
        try:
            return {"result": _number_out(_fn(a, b, p))}
        except ZeroDivisionError as exc:
            raise ZeroDivisionError(f"division by zero in {name}") from exc

    return operation


add = _binary("math.add", "Add", "+", lambda a, b, p: a + b)
subtract = _binary("math.subtract", "Subtract", "-", lambda a, b, p: a - b)
multiply = _binary("math.multiply", "Multiply", "*", lambda a, b, p: a * b)
divide = _binary("math.divide", "Divide", "/", lambda a, b, p: a / b,
                 description="Divides a by b (float result). Raises on division by zero.")
modulo = _binary("math.modulo", "Modulo", "%", lambda a, b, p: math.fmod(a, b))
power = _binary("math.power", "Power", "^", lambda a, b, p: a ** b)


@node(
    "math.sqrt",
    "Square Root",
    "Mathematics",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("result", DataType.FLOAT)],
    codegen="python",
)
def sqrt(ctx, inputs, params):
    value = _num(inputs.get("value"), "value")
    if value < 0:
        raise ValueError("cannot take the square root of a negative number")
    return {"result": math.sqrt(value)}


TRIG_FUNCTIONS = ("sin", "cos", "tan", "asin", "acos", "atan")


@node(
    "math.trig",
    "Trigonometry",
    "Mathematics",
    description="sin/cos/tan and inverses. Angles are in degrees unless 'radians' is selected.",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("result", DataType.FLOAT)],
    params=[
        ParamSpec("function", "Function", "choice", "sin", choices=TRIG_FUNCTIONS),
        ParamSpec("unit", "Unit", "choice", "degrees", choices=("degrees", "radians")),
    ],
    codegen="python",
)
def trig(ctx, inputs, params):
    name = str(params.get("function") or "sin")
    unit = str(params.get("unit") or "degrees")
    value = _num(inputs.get("value"), "value")
    if name in ("sin", "cos", "tan") and unit == "degrees":
        value = math.radians(value)
    fn = {"sin": math.sin, "cos": math.cos, "tan": math.tan,
          "asin": math.asin, "acos": math.acos, "atan": math.atan}.get(name)
    if fn is None:
        raise ValueError(f"unknown trigonometric function '{name}'")
    try:
        result = fn(value)
    except ValueError as exc:
        raise ValueError(f"{name} is undefined for {value}") from exc
    if name.startswith("a") and unit == "degrees":
        result = math.degrees(result)
    return {"result": result}


@node(
    "math.random",
    "Random Number",
    "Mathematics",
    description="Uniform random number in [min, max) or a random integer in [min, max].",
    inputs=[],
    outputs=[out("result", DataType.ANY)],
    params=[
        ParamSpec("minimum", "Minimum", "float", 0.0),
        ParamSpec("maximum", "Maximum", "float", 1.0),
        ParamSpec("integer", "Integer result", "bool", False),
        ParamSpec("seed", "Seed (optional)", "int", 0),
    ],
    pure=False,
    codegen="python",
)
def random_number(ctx, inputs, params):
    low = float(params.get("minimum", 0.0))
    high = float(params.get("maximum", 1.0))
    if high < low:
        raise ValueError("maximum must be greater than or equal to minimum")
    rng = random.Random(int(params.get("seed") or 0) or None)
    if params.get("integer"):
        return {"result": rng.randint(int(low), int(high))}
    return {"result": rng.uniform(low, high)}


@node(
    "math.clamp",
    "Clamp",
    "Mathematics",
    inputs=[inp("value", DataType.ANY), inp("minimum", DataType.ANY), inp("maximum", DataType.ANY)],
    outputs=[out("result", DataType.ANY)],
    codegen="python",
)
def clamp(ctx, inputs, params):
    value = _num(inputs.get("value"), "value")
    low = _num(inputs.get("minimum"), "minimum")
    high = _num(inputs.get("maximum"), "maximum")
    if low > high:
        raise ValueError("minimum is greater than maximum")
    return {"result": _number_out(max(low, min(high, value)))}


@node(
    "math.round",
    "Round",
    "Mathematics",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("result", DataType.ANY)],
    params=[ParamSpec("digits", "Decimal places", "int", 0, minimum=0, maximum=12)],
    codegen="python",
)
def round_number(ctx, inputs, params):
    digits = int(params.get("digits") or 0)
    value = _num(inputs.get("value"), "value")
    return {"result": _number_out(round(value, digits))}


@node(
    "math.abs",
    "Absolute Value",
    "Mathematics",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("result", DataType.ANY)],
    codegen="python",
)
def absolute(ctx, inputs, params):
    return {"result": _number_out(abs(_num(inputs.get("value"), "value")))}


@node(
    "math.aggregate",
    "Aggregate",
    "Mathematics",
    description="Sum, mean, min or max over an array of numbers.",
    inputs=[inp("values", DataType.ARRAY)],
    outputs=[out("result", DataType.ANY), out("count", DataType.INTEGER)],
    params=[ParamSpec("operation", "Operation", "choice", "sum", choices=("sum", "mean", "min", "max", "product"))],
    codegen="python",
)
def aggregate(ctx, inputs, params):
    values = inputs.get("values")
    if values is None:
        raise ValueError("'values' input is empty")
    numbers = [_num(v, "array item") for v in values]
    if not numbers:
        raise ValueError("cannot aggregate an empty array")
    op = str(params.get("operation") or "sum")
    result = {
        "sum": math.fsum,
        "mean": lambda xs: math.fsum(xs) / len(xs),
        "min": min,
        "max": max,
        "product": math.prod,
    }[op](numbers)
    return {"result": _number_out(result), "count": len(numbers)}


@node(
    "math.number_format",
    "Format Number",
    "Mathematics",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("text", DataType.STRING)],
    params=[
        ParamSpec("decimals", "Decimals", "int", 2, minimum=0, maximum=12),
        ParamSpec("thousands", "Thousands separator", "bool", False),
    ],
    codegen="python",
)
def format_number(ctx, inputs, params):
    value = _num(inputs.get("value"), "value")
    decimals = int(params.get("decimals") or 0)
    text = f"{value:,.{decimals}f}" if params.get("thousands") else f"{value:.{decimals}f}"
    return {"text": text}
