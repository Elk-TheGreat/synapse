"""Data nodes: arrays, dictionaries, strings, numbers, JSON and serialization."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from ...typesystem import DataType
from ..base import ParamSpec, inp, node, out


def _array(value: Any, name: str = "array") -> list:
    if value is None:
        raise ValueError(f"'{name}' input is empty")
    if isinstance(value, (list, tuple)):
        return list(value)
    raise ValueError(f"'{name}' must be an array, got {type(value).__name__}")


def _dict(value: Any, name: str = "dictionary") -> dict:
    if isinstance(value, dict):
        return value
    raise ValueError(f"'{name}' must be a dictionary, got {type(value).__name__}")


def _json_param(params: dict, key: str, default: Any) -> Any:
    raw = params.get(key)
    if raw in (None, ""):
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"'{key}' is not valid JSON: {exc}") from exc


# ----------------------------------------------------------------- arrays
@node(
    "data.array_create",
    "Array",
    "Data",
    description="Builds an array from up to four values.",
    inputs=[
        inp("item_0", DataType.ANY, None),
        inp("item_1", DataType.ANY, None),
        inp("item_2", DataType.ANY, None),
        inp("item_3", DataType.ANY, None),
    ],
    outputs=[out("array", DataType.ARRAY), out("length", DataType.INTEGER)],
    params=[ParamSpec("extra_items", "Extra items (JSON array)", "json", "[]")],
    keywords=("list", "collection"),
    codegen="python",
)
def array_create(ctx, inputs, params):
    items = [inputs[f"item_{i}"] for i in range(4) if inputs.get(f"item_{i}") is not None]
    extra = _json_param(params, "extra_items", [])
    if not isinstance(extra, list):
        raise ValueError("extra_items must be a JSON array")
    items.extend(extra)
    return {"array": items, "length": len(items)}


@node(
    "data.array_get",
    "Array Get",
    "Data",
    description="Reads an item by index; negative indexes count from the end.",
    inputs=[
        inp("array", DataType.ARRAY),
        inp("index", DataType.INTEGER),
        inp("default_value", DataType.ANY, None),
    ],
    outputs=[out("value", DataType.ANY), out("found", DataType.BOOLEAN)],
    codegen="python",
)
def array_get(ctx, inputs, params):
    items = _array(inputs.get("array"))
    index = int(inputs.get("index") or 0)
    try:
        return {"value": items[index], "found": True}
    except IndexError:
        return {"value": inputs.get("default_value"), "found": False}


@node(
    "data.array_append",
    "Array Append",
    "Data",
    description="Returns a new array with one item appended (or several when given an array).",
    inputs=[inp("array", DataType.ARRAY), inp("items", DataType.ANY)],
    outputs=[out("array", DataType.ARRAY), out("length", DataType.INTEGER)],
    codegen="python",
)
def array_append(ctx, inputs, params):
    items = _array(inputs.get("array"))
    addition = inputs.get("items")
    if isinstance(addition, (list, tuple)):
        items.extend(addition)
    else:
        items.append(addition)
    return {"array": items, "length": len(items)}


@node(
    "data.array_length",
    "Array Length",
    "Data",
    inputs=[inp("array", DataType.ARRAY)],
    outputs=[out("length", DataType.INTEGER), out("empty", DataType.BOOLEAN)],
    codegen="python",
)
def array_length(ctx, inputs, params):
    items = _array(inputs.get("array"))
    return {"length": len(items), "empty": not items}


@node(
    "data.array_slice",
    "Array Slice",
    "Data",
    inputs=[
        inp("array", DataType.ARRAY),
        inp("start", DataType.INTEGER, 0),
        inp("end", DataType.INTEGER, None),
    ],
    outputs=[out("array", DataType.ARRAY)],
    codegen="python",
)
def array_slice(ctx, inputs, params):
    items = _array(inputs.get("array"))
    start = int(inputs.get("start") or 0)
    end = inputs.get("end")
    return {"array": items[start:int(end)] if end is not None else items[start:]}


@node(
    "data.array_concat",
    "Array Concat",
    "Data",
    inputs=[inp("a", DataType.ARRAY), inp("b", DataType.ARRAY)],
    outputs=[out("array", DataType.ARRAY)],
    codegen="python",
)
def array_concat(ctx, inputs, params):
    return {"array": _array(inputs.get("a"), "a") + _array(inputs.get("b"), "b")}


@node(
    "data.array_sort",
    "Array Sort",
    "Data",
    inputs=[inp("array", DataType.ARRAY)],
    outputs=[out("array", DataType.ARRAY)],
    params=[
        ParamSpec("descending", "Descending", "bool", False),
        ParamSpec("by", "Sort by (key or 'value')", "text", "value"),
    ],
    codegen="python",
)
def array_sort(ctx, inputs, params):
    items = _array(inputs.get("array"))
    key_name = str(params.get("by") or "value")

    def key(item):
        if key_name in ("", "value") or not isinstance(item, dict):
            return item
        return item.get(key_name)

    try:
        ordered = sorted(items, key=key, reverse=bool(params.get("descending")))
    except TypeError as exc:
        raise ValueError(f"items cannot be sorted together: {exc}") from exc
    return {"array": ordered}


@node(
    "data.array_contains",
    "Array Contains",
    "Data",
    inputs=[inp("array", DataType.ARRAY), inp("value", DataType.ANY)],
    outputs=[out("found", DataType.BOOLEAN), out("index", DataType.INTEGER)],
    codegen="python",
)
def array_contains(ctx, inputs, params):
    items = _array(inputs.get("array"))
    target = inputs.get("value")
    for index, item in enumerate(items):
        if item == target or (item is not None and target is not None and str(item) == str(target)):
            return {"found": True, "index": index}
    return {"found": False, "index": -1}


@node(
    "data.array_join",
    "Join Array",
    "Data",
    inputs=[inp("array", DataType.ARRAY)],
    outputs=[out("text", DataType.STRING)],
    params=[ParamSpec("separator", "Separator", "text", ", ")],
    codegen="python",
)
def array_join(ctx, inputs, params):
    items = _array(inputs.get("array"))
    return {"text": str(params.get("separator", ", ")).join(str(i) for i in items)}


# ------------------------------------------------------------- dictionaries
@node(
    "data.dict_create",
    "Dictionary",
    "Data",
    description="Builds a dictionary from a JSON object or from key/value arrays.",
    inputs=[inp("keys", DataType.ARRAY, None), inp("values", DataType.ARRAY, None)],
    outputs=[out("dictionary", DataType.DICTIONARY), out("length", DataType.INTEGER)],
    params=[ParamSpec("entries", "Entries (JSON object)", "json", "{}")],
    keywords=("map", "object"),
    codegen="python",
)
def dict_create(ctx, inputs, params):
    base = _json_param(params, "entries", {})
    if not isinstance(base, dict):
        raise ValueError("entries must be a JSON object")
    result = dict(base)
    keys, values = inputs.get("keys"), inputs.get("values")
    if keys is not None:
        keys = _array(keys, "keys")
        values = _array(values, "values") if values is not None else []
        for index, key in enumerate(keys):
            result[str(key)] = values[index] if index < len(values) else None
    return {"dictionary": result, "length": len(result)}


@node(
    "data.dict_get",
    "Dictionary Get",
    "Data",
    description="Reads a key, optionally through a dotted path such as 'user.name'.",
    inputs=[inp("dictionary", DataType.DICTIONARY), inp("default_value", DataType.ANY, None)],
    outputs=[out("value", DataType.ANY), out("found", DataType.BOOLEAN)],
    params=[ParamSpec("key", "Key / path", "text", "")],
    codegen="python",
)
def dict_get(ctx, inputs, params):
    current: Any = _dict(inputs.get("dictionary"))
    key = str(params.get("key") or "")
    if not key:
        return {"value": current, "found": True}
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, (list, tuple)) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return {"value": inputs.get("default_value"), "found": False}
    return {"value": current, "found": True}


@node(
    "data.dict_set",
    "Dictionary Set",
    "Data",
    inputs=[inp("dictionary", DataType.DICTIONARY), inp("value", DataType.ANY)],
    outputs=[out("dictionary", DataType.DICTIONARY)],
    params=[ParamSpec("key", "Key", "text", ""), ParamSpec("remove", "Remove key", "bool", False)],
    codegen="python",
)
def dict_set(ctx, inputs, params):
    result = dict(_dict(inputs.get("dictionary")))
    key = str(params.get("key") or "")
    if not key:
        raise ValueError("dictionary key is empty")
    if params.get("remove"):
        result.pop(key, None)
    else:
        result[key] = inputs.get("value")
    return {"dictionary": result}


@node(
    "data.dict_keys",
    "Dictionary Keys",
    "Data",
    inputs=[inp("dictionary", DataType.DICTIONARY)],
    outputs=[out("keys", DataType.ARRAY), out("values", DataType.ARRAY), out("length", DataType.INTEGER)],
    params=[ParamSpec("sorted", "Sorted", "bool", True)],
    codegen="python",
)
def dict_keys(ctx, inputs, params):
    data = _dict(inputs.get("dictionary"))
    keys = sorted(data) if params.get("sorted") else list(data)
    return {"keys": keys, "values": [data[k] for k in keys], "length": len(keys)}


@node(
    "data.dict_merge",
    "Dictionary Merge",
    "Data",
    inputs=[inp("a", DataType.DICTIONARY), inp("b", DataType.DICTIONARY)],
    outputs=[out("dictionary", DataType.DICTIONARY)],
    params=[ParamSpec("deep", "Deep merge", "bool", True)],
    codegen="python",
)
def dict_merge(ctx, inputs, params):
    left = _dict(inputs.get("a"), "a")
    right = _dict(inputs.get("b"), "b")

    def merge(x: dict, y: dict) -> dict:
        out_value = dict(x)
        for key, value in y.items():
            if params.get("deep") and isinstance(out_value.get(key), dict) and isinstance(value, dict):
                out_value[key] = merge(out_value[key], value)
            else:
                out_value[key] = value
        return out_value

    return {"dictionary": merge(left, right)}


# ----------------------------------------------------------------- strings
@node(
    "data.string",
    "String",
    "Data",
    description="A literal string value.",
    inputs=[],
    outputs=[out("text", DataType.STRING)],
    params=[ParamSpec("value", "Value", "multiline", "")],
    codegen="python",
)
def string_literal(ctx, inputs, params):
    return {"text": str(params.get("value", ""))}


@node(
    "data.string_split",
    "Split String",
    "Data",
    inputs=[inp("text", DataType.STRING)],
    outputs=[out("parts", DataType.ARRAY)],
    params=[ParamSpec("separator", "Separator", "text", ","), ParamSpec("limit", "Max parts (0 = all)", "int", 0, minimum=0)],
    codegen="python",
)
def string_split(ctx, inputs, params):
    text = "" if inputs.get("text") is None else str(inputs.get("text"))
    limit = int(params.get("limit") or 0)
    parts = text.split(str(params.get("separator", ",")), limit - 1) if limit > 0 else text.split(str(params.get("separator", ",")))
    return {"parts": parts}


@node(
    "data.string_replace",
    "Replace String",
    "Data",
    inputs=[inp("text", DataType.STRING), inp("search", DataType.STRING), inp("replacement", DataType.STRING)],
    outputs=[out("text", DataType.STRING), out("count", DataType.INTEGER)],
    params=[ParamSpec("use_regex", "Treat search as regex", "bool", False)],
    codegen="python",
)
def string_replace(ctx, inputs, params):
    text = "" if inputs.get("text") is None else str(inputs.get("text"))
    search = "" if inputs.get("search") is None else str(inputs.get("search"))
    replacement = "" if inputs.get("replacement") is None else str(inputs.get("replacement"))
    if not search:
        return {"text": text, "count": 0}
    if params.get("use_regex"):
        try:
            result, count = re.subn(search, replacement, text)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc
        return {"text": result, "count": count}
    return {"text": text.replace(search, replacement), "count": text.count(search)}


@node(
    "data.string_transform",
    "String Transform",
    "Data",
    inputs=[inp("text", DataType.STRING)],
    outputs=[out("text", DataType.STRING)],
    params=[
        ParamSpec(
            "operation",
            "Operation",
            "choice",
            "upper",
            choices=("upper", "lower", "title", "capitalize", "trim", "reverse", "slug"),
        )
    ],
    codegen="python",
)
def string_transform(ctx, inputs, params):
    text = "" if inputs.get("text") is None else str(inputs.get("text"))
    op = str(params.get("operation") or "upper")
    if op == "upper":
        return {"text": text.upper()}
    if op == "lower":
        return {"text": text.lower()}
    if op == "title":
        return {"text": text.title()}
    if op == "capitalize":
        return {"text": text.capitalize()}
    if op == "trim":
        return {"text": text.strip()}
    if op == "reverse":
        return {"text": text[::-1]}
    return {"text": re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")}


@node(
    "data.string_substring",
    "Substring",
    "Data",
    inputs=[inp("text", DataType.STRING), inp("start", DataType.INTEGER, 0), inp("end", DataType.INTEGER, None)],
    outputs=[out("text", DataType.STRING), out("length", DataType.INTEGER)],
    codegen="python",
)
def substring(ctx, inputs, params):
    text = "" if inputs.get("text") is None else str(inputs.get("text"))
    start = int(inputs.get("start") or 0)
    end = inputs.get("end")
    result = text[start:int(end)] if end is not None else text[start:]
    return {"text": result, "length": len(result)}


@node(
    "data.string_format",
    "Format String",
    "Data",
    description="Formats a template such as 'Hello {name}' using a dictionary of values.",
    inputs=[inp("values", DataType.DICTIONARY, None), inp("text", DataType.STRING, None)],
    outputs=[out("text", DataType.STRING)],
    params=[ParamSpec("template", "Template", "multiline", "{value}")],
    codegen="python",
)
def format_string(ctx, inputs, params):
    template = inputs.get("text")
    if template is None:
        template = str(params.get("template") or "")
    values = inputs.get("values") or {}
    if not isinstance(values, dict):
        raise ValueError("'values' must be a dictionary")
    try:
        return {"text": str(template).format_map(_SafeDict(values))}
    except (KeyError, ValueError, IndexError) as exc:
        raise ValueError(f"cannot format template: {exc}") from exc


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


# ------------------------------------------------------------------ numbers
@node(
    "data.to_number",
    "To Number",
    "Data",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("number", DataType.ANY), out("ok", DataType.BOOLEAN)],
    params=[ParamSpec("integer", "Force integer", "bool", False)],
    codegen="python",
)
def to_number(ctx, inputs, params):
    raw = inputs.get("value")
    try:
        if isinstance(raw, bool):
            number: Any = int(raw)
        elif isinstance(raw, (int, float)):
            number = raw
        elif isinstance(raw, str):
            text = raw.strip()
            number = int(text) if params.get("integer") and re.fullmatch(r"[-+]?\d+", text) else float(text)
        else:
            raise ValueError(f"{type(raw).__name__} is not numeric")
    except (TypeError, ValueError):
        return {"number": None, "ok": False}
    if params.get("integer"):
        number = int(number)
    return {"number": number, "ok": True}


@node(
    "data.to_string",
    "To String",
    "Data",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("text", DataType.STRING)],
    params=[ParamSpec("pretty", "Pretty print JSON", "bool", False)],
    codegen="python",
)
def to_string(ctx, inputs, params):
    value = inputs.get("value")
    if isinstance(value, (dict, list)):
        return {"text": json.dumps(value, indent=2 if params.get("pretty") else None, default=str, ensure_ascii=False)}
    return {"text": "" if value is None else str(value)}


@node(
    "data.to_boolean",
    "To Boolean",
    "Data",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("value", DataType.BOOLEAN)],
    codegen="python",
)
def to_boolean(ctx, inputs, params):
    value = inputs.get("value")
    if isinstance(value, str):
        return {"value": value.strip().lower() in ("1", "true", "yes", "on")}
    return {"value": bool(value)}


@node(
    "data.type_of",
    "Type Of",
    "Data",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("type", DataType.STRING)],
    codegen="python",
)
def type_of(ctx, inputs, params):
    from ...typesystem import infer_type

    return {"type": infer_type(inputs.get("value")).value}


# -------------------------------------------------------------------- JSON
@node(
    "data.json_parse",
    "Parse JSON",
    "Data",
    inputs=[inp("text", DataType.STRING)],
    outputs=[out("value", DataType.ANY), out("ok", DataType.BOOLEAN)],
    codegen="python",
)
def json_parse(ctx, inputs, params):
    raw = inputs.get("text")
    if raw is None:
        raise ValueError("'text' input is empty")
    try:
        return {"value": json.loads(str(raw)), "ok": True}
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}") from exc


@node(
    "data.json_stringify",
    "JSON Stringify",
    "Data",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("text", DataType.STRING)],
    params=[ParamSpec("indent", "Indent", "int", 0, minimum=0, maximum=8)],
    codegen="python",
)
def json_stringify(ctx, inputs, params):
    indent = int(params.get("indent") or 0) or None
    try:
        text = json.dumps(inputs.get("value"), indent=indent, default=_json_default, ensure_ascii=False)
    except TypeError as exc:
        raise ValueError(f"value cannot be represented as JSON: {exc}") from exc
    return {"text": text}


def _json_default(value: Any) -> Any:
    from ...typesystem import FileRef

    if isinstance(value, FileRef):
        return str(value.path)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if hasattr(value, "to_bytes"):
        return base64.b64encode(value.to_bytes()).decode("ascii")
    return str(value)


@node(
    "data.json_query",
    "JSON Query",
    "Data",
    description="Reads a dotted path from parsed JSON (e.g. 'items.0.name').",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("value", DataType.ANY), out("found", DataType.BOOLEAN)],
    params=[ParamSpec("path", "Path", "text", "")],
    codegen="python",
)
def json_query(ctx, inputs, params):
    current = inputs.get("value")
    path = str(params.get("path") or "")
    if not path:
        return {"value": current, "found": True}
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return {"value": None, "found": False}
    return {"value": current, "found": True}


# ----------------------------------------------------------- serialization
@node(
    "data.serialize",
    "Serialize",
    "Data",
    description="Encodes a value as JSON, base64 or hex text.",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("text", DataType.STRING)],
    params=[ParamSpec("format", "Format", "choice", "json", choices=("json", "base64", "hex"))],
    codegen="python",
)
def serialize(ctx, inputs, params):
    value = inputs.get("value")
    fmt = str(params.get("format") or "json")
    if fmt == "base64":
        raw = value if isinstance(value, bytes) else bytes(str(value), "utf-8")
        return {"text": base64.b64encode(raw).decode("ascii")}
    if fmt == "hex":
        raw = value if isinstance(value, bytes) else bytes(str(value), "utf-8")
        return {"text": raw.hex()}
    return {"text": json.dumps(value, default=_json_default, ensure_ascii=False)}


@node(
    "data.deserialize",
    "Deserialize",
    "Data",
    inputs=[inp("text", DataType.STRING)],
    outputs=[out("value", DataType.ANY)],
    params=[ParamSpec("format", "Format", "choice", "json", choices=("json", "base64", "hex"))],
    codegen="python",
)
def deserialize(ctx, inputs, params):
    text = "" if inputs.get("text") is None else str(inputs.get("text"))
    fmt = str(params.get("format") or "json")
    try:
        if fmt == "base64":
            return {"value": base64.b64decode(text.encode("ascii"))}
        if fmt == "hex":
            return {"value": bytes.fromhex(text)}
        return {"value": json.loads(text)}
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot decode {fmt}: {exc}") from exc
