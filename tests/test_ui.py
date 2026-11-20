"""Offscreen smoke tests for the desktop shell and the canvas."""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QPointF

from conftest import build_sum_graph
from synapse.application.canvas.scene import GraphScene
from synapse.application.main_window import MainWindow
from synapse.project import AppDatabase


def _wait(qapp, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


@pytest.fixture
def window(qapp, tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    win = MainWindow(db)
    yield win
    win._set_dirty(False)
    win.close()
    qapp.processEvents()
    db.close()


def test_window_starts_on_welcome(window):
    assert window.project is None
    assert window.welcome is not None
    window.show()
    window.close()


def test_new_project_builds_canvas_and_tabs(window, qapp, tmp_path):
    window.new_project("Arithmetic", "UI Demo", str(tmp_path))
    assert window.project is not None
    assert window.scene is not None and len(window.scene.node_items) >= 3
    assert window.tabs.count() == 1
    assert window.project.main_graph.id in window.project.graphs
    window.run_graph()
    assert _wait(
        qapp,
        lambda: not window.runner.is_running()
        and "run finished" in window.console.output.toPlainText().lower(),
    )
    log = window.console.output.toPlainText().lower()
    assert "ok" in log and "failed" in log
    assert window.console.last_result is not None
    assert window.console.last_result.outputs


def test_theme_switch(window, qapp, tmp_path):
    window.new_project("Blank", "Theme Demo", str(tmp_path))
    window.set_theme("light")
    assert window.theme_name == "light"
    window.set_theme("dark")
    assert window.theme_name == "dark"


def test_canvas_add_undo_redo(qapp, registry):
    graph = build_sum_graph(registry, 1, 2)
    scene = GraphScene(graph)
    start = len(scene.graph.nodes)
    item = scene.add_node("math.sqrt", QPointF(30, 30))
    assert item is not None and len(scene.graph.nodes) == start + 1
    assert len(scene.node_items) == start + 1
    scene.undo()
    assert len(scene.graph.nodes) == start
    scene.redo()
    assert len(scene.graph.nodes) == start + 1
    scene.add_node("math.sqrt", QPointF(20, 20))
    scene.add_node("not.a.node", QPointF(0, 0))
    assert len(scene.graph.nodes) == start + 2


def test_canvas_copy_paste_and_delete(qapp, registry):
    graph = build_sum_graph(registry, 3, 3)
    scene = GraphScene(graph)
    ids = list(scene.graph.nodes)
    scene.select_all_nodes()
    scene.copy_selection()
    before = len(scene.graph.nodes)
    scene.paste()
    assert len(scene.graph.nodes) == before + len(ids)
    pasted = set(scene.selected_node_ids())
    assert pasted and pasted.isdisjoint(ids)
    scene.delete_selection()
    assert len(scene.graph.nodes) == before
