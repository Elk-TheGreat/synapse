# Writing plugins

A plugin is a folder containing `plugin.json` and a Python module (or a set of script node specs). Plugins add nodes, categories and configuration UI to SYNAPSE.

## Folder layout

```
my-plugin/
  plugin.json
  nodes.py
```

## Manifest

```json
{
  "name": "acme.text-tools",
  "display_name": "ACME Text Tools",
  "version": "1.0.0",
  "api_version": 1,
  "description": "Extra string nodes",
  "author": "ACME",
  "entry": "nodes.py",
  "runtime": "python",
  "permissions": ["files"],
  "dependencies": [],
  "keywords": ["text"]
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `name` | yes | Unique id; node ids become `ext.<name>.<type_id>` |
| `display_name` | no | Category/showcase name |
| `version` | yes | Semantic version string |
| `api_version` | yes | Must equal `1` for this release |
| `description` | no | Shown in the plugin manager |
| `author` | no | Shown in the plugin manager |
| `entry` | yes for `python` | Module file relative to the plugin folder |
| `runtime` | yes | `python` or `script` |
| `permissions` | no | Subset of `files`, `network`, `process`, `scripts` |
| `dependencies` | no | Informational package requirements |
| `keywords` | no | Search terms |

## Python runtime

```python
from synapse.extensions.api import PluginAPI
from synapse.nodes.base import inp, out
from synapse.nodes.registry import NodeRegistry
from synapse.typesystem import DataType

def register(registry: NodeRegistry, api: PluginAPI) -> None:
    @api.node(
        "shout",
        "Shout",
        "Text",
        description="Upper-cases text and adds an exclamation mark.",
        inputs=[inp("text", DataType.STRING)],
        outputs=[out("text", DataType.STRING)],
        keywords=("upper", "text"),
    )
    async def shout(ctx, inputs, params):
        return {"text": str(inputs.get("text") or "").upper() + "!"}
```

Each Python plugin module must define `register(registry, api)`. `api.node` is a decorator that registers and returns the function. Use `api.register(...)` for dynamic registration. The node receives:

- `ctx` — `NodeContext`: `ctx.security`, `ctx.variables`, `ctx.log(message, level)`, `await ctx.run_blocking(fn, ...)`, `await ctx.call_function(function_id, inputs)`, `ctx.project_dir`, `ctx.node`, `ctx.definition`.
- `inputs` — resolved values by port name.
- `params` — configured parameter values by name.

Return a mapping of output port name to value. Raise an exception to fail the node; the engine records it with the node id and traceback.

`ParamSpec(name, label, kind, default, choices=..., minimum=..., maximum=..., description=..., secret=False)` drives the inspector. Kinds: `text`, `multiline`, `int`, `float`, `bool`, `choice`, `code`, `file`, `json`.

### Permissions

`api.require("network")` raises `PermissionDenied` unless the manifest declared it. Permission checks protect users from accidental capability use; they do not sandbox Python. State clearly in your README what the plugin does.

## Script runtime

With `"runtime": "script"` the manifest lists nodes with inline code instead of a Python entry module:

```json
{
  "name": "hello-script",
  "display_name": "Hello Script",
  "version": "1.0.0",
  "api_version": 1,
  "runtime": "script",
  "permissions": [],
  "nodes": [
    {
      "type_id": "hello",
      "name": "Hello",
      "inputs": [{"name": "name", "type": "string"}],
      "outputs": [{"name": "text", "type": "string"}],
      "code": "result = {'text': 'Hello ' + str(inputs.get('name', 'world'))}"
    }
  ]
}
```

Each execution runs in the isolated interpreter with the script import allow-list and timeout. Script nodes cannot call functions, blocking helpers or the filesystem outside the standard-library allow-list.

## Installing

- **In the app:** Extensions → Install… → choose the plugin folder. Enable it, then the nodes appear in the library and registry.
- **By hand:** copy the folder into the user plugin directory (shown in the Extensions dialog) and restart or reload.

The manager checks `api_version`, refuses duplicate/built-in ids and contains load failures. Bundled plugins under `synapse/extensions/bundled/` cannot be removed, only disabled.

## Versioning and compatibility

Bump `version` for changes. `api_version` only changes when the plugin API breaks. Plugins that need a newer host API are refused with a message rather than partially loaded. Keep node `type_id` stable: saved projects reference the namespaced id.

## Testing a plugin

```python
from synapse.nodes.registry import create_registry
from synapse.extensions.manager import PluginManager

registry = create_registry()
manager = PluginManager(roots=["path/to/plugins"])
errors = manager.load_enabled(registry)
assert not errors
node = registry.require("ext.acme.text-tools.shout")
```

Execute nodes through the normal executor (see `tests/test_extensions.py`), and test failure paths: missing manifest fields, bad imports, incompatible API version.
