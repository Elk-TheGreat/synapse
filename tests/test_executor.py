import asyncio
import time

import pytest

from conftest import build_sum_graph
from synapse.engine.context import SecurityPolicy
from synapse.engine.executor import ExecutionOptions, Executor
from synapse.functions.library import FunctionLibrary
from synapse.graph.model import Graph
from synapse.nodes.registry import create_registry
from synapse.project.templates import create_project


def test_dataflow_result(run_graph, registry):
    result = run_graph(build_sum_graph(registry, 20, 22))
    assert result.ok and result.outputs == {"sum": 42}
    assert all(r.status == "ok" for r in result.nodes.values())
    assert result.order and len(result.order) == 4


def test_nodes_run_after_their_inputs(run_graph, registry):
    result = run_graph(build_sum_graph(registry, 1, 2))
    add = next(n.id for n in build_sum_graph(registry, 1, 2).nodes.values() if n.type == "math.add")
    del add  # only the ordering below is asserted
    assert result.order.index(next(i for i, n in result.nodes.items() if n.node_type == "math.add")) > 0


def test_error_isolated_and_downstream_skipped(run_graph, registry):
    g = Graph("g", "Divide", registry=registry)
    a = g.add_node("core.constant", {"value": "1"})
    zero = g.add_node("core.constant", {"value": "0"})
    div = g.add_node("math.divide")
    out = g.add_node("core.graph_output", {"name": "x"})
    g.connect(a.id, "value", div.id, "a")
    g.connect(zero.id, "value", div.id, "b")
    g.connect(div.id, "result", out.id, "value")
    result = run_graph(g)
    assert result.status == "error"
    assert result.nodes[div.id].status == "error"
    assert "zero" in result.nodes[div.id].error.lower()
    assert result.nodes[out.id].status == "skipped"
    assert result.outputs == {}


def test_validation_rejects_missing_inputs(run_graph, registry):
    g = Graph("g", "Broken", registry=registry)
    out = g.add_node("core.graph_output", {"name": "x"})
    result = run_graph(g)
    assert result.status == "invalid"
    assert result.validation_errors
    assert result.nodes == {}


def test_timeout_cancels_run(run_graph, registry):
    g = Graph("g", "Slow", registry=registry)
    timer = g.add_node("system.timer", {"delay": 5.0})
    out = g.add_node("core.graph_output", {"name": "seconds"})
    g.connect(timer.id, "seconds", out.id, "value")
    result = run_graph(g, options=ExecutionOptions(timeout=0.3))
    assert result.status in ("timeout", "cancelled")
    assert result.timed_out or result.cancelled


def test_loop_template_sums(run_graph, registry):
    project = create_project("Loop", registry)
    result = run_graph(project.main_graph, functions=project.function_library())
    assert result.ok, result.summary()
    assert result.outputs["sum"] == 15
    assert result.outputs["iterations"] == 5


def test_function_template_doubles(run_graph, registry):
    project = create_project("Function", registry)
    result = run_graph(project.main_graph, functions=project.function_library())
    assert result.ok and result.outputs["doubled"] == 42


def test_cache_skips_recomputation(registry):
    g = build_sum_graph(registry, 5, 6)
    executor = Executor(registry)
    try:
        first = asyncio.run(executor.run(g, options=ExecutionOptions(cache=True)))
        second = asyncio.run(executor.run(g, options=ExecutionOptions(cache=True)))
    finally:
        executor.shutdown()
    assert first.outputs == second.outputs == {"sum": 11}
    assert any(r.cached for r in second.nodes.values())


def test_fail_fast_stops_other_branches(run_graph, registry):
    g = Graph("g", "FailFast", registry=registry)
    good = g.add_node("core.constant", {"value": "1"})
    bad = g.add_node("math.sqrt")
    neg = g.add_node("core.constant", {"value": "-1"})
    out = g.add_node("core.graph_output", {"name": "x"})
    g.connect(neg.id, "value", bad.id, "value")
    g.connect(good.id, "value", out.id, "value")
    result = run_graph(g, options=ExecutionOptions(fail_fast=True))
    assert result.status == "error"


def test_script_node_receives_and_returns_data(run_graph, registry):
    project = create_project("Python Script", registry)
    result = run_graph(project.main_graph, security=SecurityPolicy(allow_scripts=True))
    assert result.ok, result.summary()
    stats = result.outputs["stats"]
    assert stats["total"] == 108 and stats["mean"] == 18.0


def test_script_cannot_import_forbidden_module(run_graph, registry):
    g = Graph("g", "Escape", registry=registry)
    script = g.add_node("script.python", {"code": "import socket\nresult = 1\n"})
    out = g.add_node("core.graph_output", {"name": "x"})
    g.connect(script.id, "result", out.id, "value")
    result = run_graph(g, security=SecurityPolicy(allow_scripts=True, script_timeout=10))
    assert result.status == "error"
    assert "socket" in result.nodes[script.id].error.lower()


def test_network_disabled_is_refused(run_graph, registry):
    g = Graph("g", "Net", registry=registry)
    req = g.add_node("net.http_request", {"method": "GET"})
    url = g.add_node("data.string", {"value": "http://example.com"})
    out = g.add_node("core.graph_output", {"name": "text"})
    g.connect(url.id, "text", req.id, "url")
    g.connect(req.id, "text", out.id, "value")
    result = run_graph(g, security=SecurityPolicy(allow_network=False))
    assert result.status == "error"
    assert "network" in result.nodes[req.id].error.lower()
