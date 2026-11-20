import asyncio
import json

import pytest

from synapse.engine.executor import ExecutionOptions, Executor
from synapse.project import (
    FORMAT,
    FORMAT_VERSION,
    AppDatabase,
    Project,
    ProjectError,
    ProjectStore,
    TEMPLATES,
    create_project,
)


def _run(project, registry, tmp_path):
    executor = Executor(
        registry,
        functions=project.function_library(),
        project_dir=str(tmp_path),
    )
    try:
        return asyncio.run(executor.run(project.main_graph, options=ExecutionOptions()))
    finally:
        executor.shutdown()


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_every_template_executes(registry, template, tmp_path):
    project = create_project(template, registry)
    result = _run(project, registry, tmp_path)
    assert result.ok, (template, result.summary(), result.errors)


def test_save_and_load_roundtrip(registry, tmp_path):
    project = create_project("Loop", registry)
    store = ProjectStore(autosave_dir=str(tmp_path / "autosave"))
    path = store.save(project, tmp_path / "demo")
    assert path.suffix == ".synapse" and path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["format"] == FORMAT and raw["format_version"] == FORMAT_VERSION

    loaded = store.load(path, registry=registry)
    assert loaded.name == project.name
    assert set(loaded.graphs) == set(project.graphs)
    assert [f.name for f in loaded.functions] == [f.name for f in project.functions]
    assert loaded.settings.concurrency == project.settings.concurrency
    assert _run(loaded, registry, tmp_path).ok


def test_autosave_and_recovery(registry, tmp_path):
    store = ProjectStore(autosave_dir=str(tmp_path / "autosave"))
    project = create_project("Arithmetic", registry)
    path = store.save(project, tmp_path / "live.synapse")
    store.autosave(project)
    recoveries = store.recoveries()
    assert recoveries and recoveries[0]["path"] == str(path)
    recovered = store.load_recovery(recoveries[0]["snapshot"], registry=registry)
    assert recovered.name == project.name
    store.discard_recovery(recoveries[0]["snapshot"])
    assert store.recoveries() == []


def test_invalid_project_file_is_reported(registry, tmp_path):
    store = ProjectStore(autosave_dir=str(tmp_path / "autosave"))
    bad = tmp_path / "bad.synapse"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProjectError):
        store.load(bad, registry=registry)


def test_unknown_format_version_rejected(registry, tmp_path):
    store = ProjectStore(autosave_dir=str(tmp_path / "autosave"))
    path = tmp_path / "future.synapse"
    path.write_text(json.dumps({"format": FORMAT, "format_version": 99, "project": {}}), encoding="utf-8")
    with pytest.raises(ProjectError):
        store.load(path, registry=registry)


def test_database_recent_and_settings(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    try:
        db.set("theme", "light")
        assert db.get("theme") == "light"
        db.add_recent("/tmp/demo.synapse", "Demo")
        recent = db.recent()
        assert recent and recent[0]["name"] == "Demo"
    finally:
        db.close()


def test_multiple_graphs_and_functions_persist(registry, tmp_path):
    project = Project(name="Multi")
    project.bind_registry(registry)
    project.add_graph("Extra", graph_id="g_extra")
    store = ProjectStore(autosave_dir=str(tmp_path / "autosave"))
    path = store.save(project, tmp_path / "multi.synapse")
    loaded = store.load(path, registry=registry)
    assert set(loaded.graphs) == {"g_main", "g_extra"}
