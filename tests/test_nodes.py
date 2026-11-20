"""Every tested node is executed for real through the engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synapse.engine.context import SecurityPolicy
from synapse.engine.executor import ExecutionOptions, Executor
from synapse.graph.model import Graph


def _constant(g, value):
    if isinstance(value, str):
        return g.add_node("core.constant", {"value_type": "string", "value": value})
    return g.add_node("core.constant", {"value_type": "json", "value": json.dumps(value)})


def evaluate(registry, type_id, params=None, inputs=None, *, security=None):
    g = Graph("g", "Node", registry=registry)
    node = g.add_node(type_id, params or {})
    for port, value in (inputs or {}).items():
        source = _constant(g, value)
        g.connect(source.id, "value", node.id, port)
    ports = g.output_ports(node)
    for port in ports:
        out = g.add_node("core.graph_output", {"name": port.name})
        g.connect(node.id, port.name, out.id, "value")
    executor = Executor(registry, security=security)
    try:
        return executor_run(executor, g).outputs
    finally:
        executor.shutdown()


def executor_run(executor, graph):
    import asyncio

    return asyncio.run(executor.run(graph, options=ExecutionOptions()))


@pytest.mark.parametrize(
    "type_id,inputs,params,expected",
    [
        ("math.add", {"a": 2, "b": 3}, {}, {"result": 5}),
        ("math.subtract", {"a": 9, "b": 4}, {}, {"result": 5}),
        ("math.multiply", {"a": 6, "b": 7}, {}, {"result": 42}),
        ("math.divide", {"a": 9, "b": 3}, {}, {"result": 3.0}),
        ("math.modulo", {"a": 9, "b": 4}, {}, {"result": 1}),
        ("math.power", {"a": 2, "b": 8}, {}, {"result": 256}),
        ("math.sqrt", {"value": 81}, {}, {"result": 9.0}),
        ("math.round", {"value": 3.14159}, {"digits": 2}, {"result": 3.14}),
        ("math.abs", {"value": -7}, {}, {"result": 7}),
    ],
)
def test_math_nodes(registry, type_id, inputs, params, expected):
    assert evaluate(registry, type_id, params, inputs) == expected


def test_numeric_strings_are_accepted(registry):
    assert evaluate(registry, "math.add", {}, {"a": "2", "b": "3.5"}) == {"result": 5.5}


def test_math_rejects_text(registry):
    result = evaluate(registry, "math.add", {}, {"a": "hello", "b": 1})
    assert result == {}


def test_logic_if_and_compare(registry):
    assert evaluate(registry, "logic.if", {}, {"condition": True, "true_value": "yes", "false_value": "no"}) == {"result": "yes"}
    assert evaluate(registry, "logic.compare", {"operator": ">="}, {"a": 4, "b": 4}) == {"result": True}
    assert evaluate(registry, "logic.and", {}, {"a": True, "b": True, "c": False}) == {"result": False}
    assert evaluate(registry, "logic.not", {}, {"value": 0}) == {"result": True}


def test_switch_matches_case(registry):
    result = evaluate(registry, "logic.switch", {"cases": "a,b,c"}, {"selector": "b", "case_1": "B"})
    assert result["result"] == "B"
    assert result["matched_index"] == 1


def test_json_nodes(registry):
    parsed = evaluate(registry, "data.json_parse", {}, {"text": '{"a": [1, 2]}'})
    assert parsed["value"] == {"a": [1, 2]} and parsed["ok"] is True
    assert evaluate(registry, "data.json_query", {"path": "a.1"}, {"value": {"a": [3, 4]}})["value"] == 4
    assert evaluate(registry, "data.json_stringify", {}, {"value": {"b": 1}})["text"] == '{"b": 1}'


def test_string_nodes(registry):
    assert evaluate(registry, "data.string_split", {"separator": ","}, {"text": "a,b,c"})["parts"] == ["a", "b", "c"]
    assert evaluate(registry, "data.string_transform", {"operation": "upper"}, {"text": "abc"})["text"] == "ABC"
    assert evaluate(registry, "data.string_replace", {"use_regex": False}, {"text": "a-b", "search": "-", "replacement": "+"})["text"] == "a+b"


def test_dictionary_and_array_nodes(registry):
    assert evaluate(registry, "data.dict_get", {"key": "user.name"}, {"dictionary": {"user": {"name": "Ada"}}})["value"] == "Ada"
    assert evaluate(registry, "data.array_length", {}, {"array": [1, 2, 3]})["length"] == 3
    assert evaluate(registry, "data.array_get", {}, {"array": [10, 20], "index": 1})["value"] == 20
    assert evaluate(registry, "data.array_sort", {}, {"array": [3, 1, 2]})["array"] == [1, 2, 3]


def test_type_conversion_nodes(registry):
    assert evaluate(registry, "data.to_number", {}, {"value": "42"})["number"] == 42
    assert evaluate(registry, "data.to_string", {}, {"value": 42})["text"] == "42"
    assert evaluate(registry, "data.to_boolean", {}, {"value": "true"})["value"] is True


def test_files_roundtrip(registry, tmp_path):
    security = SecurityPolicy(file_roots=[str(tmp_path)])
    target = tmp_path / "hello.txt"
    write = evaluate(registry, "files.write", {}, {"path": str(target), "content": "hello synapse"}, security=security)
    assert write["size"] == 13
    read = evaluate(registry, "files.read", {}, {"path": str(target)}, security=security)
    assert read["text"] == "hello synapse"
    listing = evaluate(registry, "files.list", {}, {"path": str(tmp_path)}, security=security)
    assert "hello.txt" in listing["names"]
    copied = evaluate(registry, "files.copy", {}, {"source": str(target), "destination": str(tmp_path / "copy.txt")}, security=security)
    assert Path(getattr(copied["path"], "path", copied["path"])).exists()
    moved = evaluate(registry, "files.move", {}, {"source": str(tmp_path / "copy.txt"), "destination": str(tmp_path / "moved.txt")}, security=security)
    assert Path(getattr(moved["path"], "path", moved["path"])).exists()
    assert evaluate(registry, "files.delete", {}, {"path": str(tmp_path / "moved.txt")}, security=security)["deleted"] is True
    assert not (tmp_path / "moved.txt").exists()


def test_files_outside_roots_refused(registry, tmp_path):
    security = SecurityPolicy(file_roots=[str(tmp_path)])
    result = evaluate(registry, "files.read", {}, {"path": "/etc/hostname"}, security=security)
    assert result == {}


def test_graphics_pipeline(registry, tmp_path):
    security = SecurityPolicy(file_roots=[str(tmp_path)])
    g = Graph("g", "Graphics", registry=registry)
    draw = g.add_node(
        "graphics.draw",
        {
            "width": 32,
            "height": 16,
            "background": "#112233",
            "shapes": [{"type": "rect", "xy": [2, 2, 10, 10], "fill": "#ff0000"}],
        },
    )
    target = str(tmp_path / "out.png")
    path = _constant(g, target)
    export = g.add_node("graphics.export", {"format": "png"})
    out = g.add_node("core.graph_output", {"name": "file"})
    g.connect(draw.id, "image", export.id, "image")
    g.connect(path.id, "value", export.id, "path")
    g.connect(export.id, "path", out.id, "value")
    executor = Executor(registry, security=security)
    try:
        result = executor_run(executor, g)
    finally:
        executor.shutdown()
    assert result.ok, result.summary()
    assert result.nodes[draw.id].outputs["width"] == 32
    assert result.nodes[draw.id].outputs["height"] == 16
    assert Path(target).exists() and Path(target).stat().st_size > 0
    assert result.nodes[export.id].outputs["format"] == "png"


def test_system_nodes(registry):
    assert evaluate(registry, "system.info") ["platform"]
    uuid_value = evaluate(registry, "system.uuid")["value"]
    assert len(uuid_value) >= 32
    assert evaluate(registry, "system.env_get", {"name": "PATH"})["found"] is True


def test_variable_set_returns_value(registry):
    assert evaluate(registry, "core.variable_set", {"name": "total"}, {"value": 7}) == {"value": 7}


def test_log_node_passes_through(registry):
    g = Graph("g", "Log", registry=registry)
    log = g.add_node("core.log", {"label": "demo"})
    value = _constant(g, 5)
    out = g.add_node("core.graph_output", {"name": "v"})
    g.connect(value.id, "value", log.id, "value")
    g.connect(log.id, "value", out.id, "value")
    executor = Executor(registry)
    try:
        result = executor_run(executor, g)
    finally:
        executor.shutdown()
    assert result.outputs == {"v": 5}
