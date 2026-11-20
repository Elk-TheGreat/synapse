"""Shared fixtures for the SYNAPSE test suite."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from synapse.engine.executor import ExecutionOptions, Executor  # noqa: E402
from synapse.graph.model import Graph  # noqa: E402
from synapse.nodes.registry import create_registry  # noqa: E402


@pytest.fixture(scope="session")
def registry():
    return create_registry()


@pytest.fixture
def graph(registry):
    return Graph("g_test", "Test", registry=registry)


@pytest.fixture
def run_graph(registry):
    def _run(g, *, inputs=None, options=None, debugger=None, functions=None, security=None):
        executor = Executor(registry, functions, security=security)
        opts = options if options is not None else ExecutionOptions()
        try:
            return asyncio.run(executor.run(g, inputs=inputs or {}, options=opts, debugger=debugger))
        finally:
            executor.shutdown()

    return _run


def build_sum_graph(registry, a_value, b_value):
    g = Graph("g_sum", "Sum", registry=registry)
    a = g.add_node("core.constant", {"value": a_value})
    b = g.add_node("core.constant", {"value": b_value})
    add = g.add_node("math.add")
    out = g.add_node("core.graph_output", {"name": "sum"})
    g.connect(a.id, "value", add.id, "a")
    g.connect(b.id, "value", add.id, "b")
    g.connect(add.id, "result", out.id, "value")
    return g


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app
