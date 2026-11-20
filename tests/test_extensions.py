import asyncio
import json

from synapse.engine.executor import ExecutionOptions, Executor
from synapse.extensions.manager import PluginManager, bundled_plugin_dir
from synapse.graph.model import Graph
from synapse.nodes.registry import create_registry


def test_bundled_plugins_discover_and_load(tmp_path):
    manager = PluginManager(roots=[tmp_path / "empty"])
    records = manager.discover()
    assert records == []
    manager = PluginManager()
    records = manager.discover()
    names = {record.manifest.name for record in records}
    assert {"stats", "text-tools"} <= names
    assert all(record.error is None for record in records if record.enabled)

    registry = create_registry()
    before = len(registry.all())
    failures = manager.load_enabled(registry)
    assert failures == {}
    assert len(registry.all()) == before + 5
    ext = [d for d in registry.all() if d.type_id.startswith("ext.")]
    assert len(ext) == 5 and all(d.category for d in ext)


def test_plugin_node_executes(tmp_path):
    manager = PluginManager()
    manager.discover()
    registry = create_registry()
    assert manager.load_enabled(registry) == {}
    definition = next(d for d in registry.all() if d.type_id.endswith("stats.describe"))

    g = Graph("g", "Plugin", registry=registry)
    data = g.add_node("data.array_create", {"extra_items": "[1, 2, 3, 4]"})
    describe = g.add_node(definition.type_id)
    out = g.add_node("core.graph_output", {"name": "mean"})
    g.connect(data.id, "array", describe.id, "values")
    g.connect(describe.id, "mean", out.id, "value")
    executor = Executor(registry)
    try:
        result = asyncio.run(executor.run(g, options=ExecutionOptions()))
    finally:
        executor.shutdown()
    assert result.ok, result.summary()
    assert result.outputs == {"mean": 2.5}


def test_incompatible_manifest_is_reported(tmp_path):
    plugin = tmp_path / "future"
    plugin.mkdir()
    (plugin / "plugin.json").write_text(json.dumps({
        "name": "future", "version": "1.0.0", "api_version": 999,
        "entry": "nodes.py", "runtime": "python",
    }), encoding="utf-8")
    manager = PluginManager(roots=[tmp_path])
    records = manager.discover()
    assert len(records) == 1
    record = records[0]
    assert not record.enabled
    assert "api" in (record.error or "").lower()


def test_broken_plugin_does_not_block_others(tmp_path):
    plugin = tmp_path / "broken"
    plugin.mkdir()
    (plugin / "plugin.json").write_text(json.dumps({
        "name": "broken", "version": "1.0.0", "api_version": 1,
        "entry": "nodes.py", "runtime": "python",
    }), encoding="utf-8")
    (plugin / "nodes.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    manager = PluginManager(roots=[tmp_path])
    manager.discover()
    registry = create_registry()
    failures = manager.load_enabled(registry)
    assert "broken" in failures and "boom" in failures["broken"]
    assert len(registry.all()) == len(create_registry().all())


def test_install_and_remove_plugin(tmp_path):
    source = tmp_path / "src" / "hello"
    source.mkdir(parents=True)
    (source / "plugin.json").write_text(json.dumps({
        "name": "hello", "version": "1.0.0", "api_version": 1,
        "entry": "nodes.py", "runtime": "python",
    }), encoding="utf-8")
    (source / "nodes.py").write_text(
        "def register(registry, api):\n"
        "    @api.node('hello.world', 'World', 'Test')\n"
        "    def world(ctx, inputs, params):\n"
        "        return {'text': 'hello'}\n",
        encoding="utf-8",
    )
    manager = PluginManager(roots=[bundled_plugin_dir(), tmp_path / "plugins"]) 
    manager.user_dir = tmp_path / "plugins"
    record = manager.install(source)
    assert record.manifest.name == "hello"
    manager.discover()
    assert manager.get("hello") is not None
    manager.remove("hello")
    assert manager.get("hello") is None
