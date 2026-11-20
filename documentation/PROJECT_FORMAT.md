# Project format

A SYNAPSE project is a single UTF-8 JSON file with the suffix `.synapse`. The schema is versioned; readers refuse files from a newer format instead of guessing.

- `format`: `"synapse.project"`
- `format_version`: `1`
- Readers accept version `1`; unknown top-level keys are preserved in `metadata` only if placed there.

## Top level

```json
{
  "format": "synapse.project",
  "format_version": 1,
  "id": "prj_1a2b3c4d5e6f",
  "name": "My project",
  "description": "",
  "created": 1760000000.0,
  "modified": 1760000123.4,
  "settings": { "...": "..." },
  "graphs": [ { "...": "..." } ],
  "functions": [ { "...": "..." } ],
  "assets": [],
  "dependencies": [],
  "metadata": {}
}
```

| Field | Meaning |
| --- | --- |
| `id` | Stable project identifier (`prj_` + 12 hex chars) |
| `name`, `description` | Human-readable metadata |
| `created`, `modified` | Unix timestamps (seconds) |
| `settings` | Per-project settings and security policy (below) |
| `graphs` | One or more graph documents; the first is the main graph |
| `functions` | Reusable function definitions, each containing its own graph |
| `assets` | Asset manifest entries (relative paths preferred) |
| `dependencies` | Free-form package/plugin requirements |
| `metadata` | Application-defined extras; preserved across saves |

## Settings

```json
{
  "theme": "dark",
  "accent": "#5ac8fa",
  "autosave_seconds": 60,
  "run_timeout": 120.0,
  "node_timeout": 60.0,
  "max_steps": 20000,
  "concurrency": 8,
  "allow_network": true,
  "allow_file_write": true,
  "allow_process": false,
  "allow_scripts": true,
  "file_roots": ["/home/user/projects/demo"],
  "allowed_hosts": [],
  "editor": {}
}
```

`autosave_seconds` is clamped to at least 5; `concurrency` to 1–64. `file_roots` is the only place file nodes may read or write. `allowed_hosts` empty means any host once network access is enabled; otherwise exact hosts and subdomains are allowed.

## Graph document

```json
{
  "id": "g_main",
  "name": "Main",
  "description": "",
  "nodes": [],
  "edges": [],
  "frames": [],
  "variables": {},
  "inputs": [],
  "outputs": [],
  "metadata": {}
}
```

### Node

```json
{
  "id": "n_4e9c1559af37",
  "type": "math.add",
  "params": {"value_type": "auto", "value": "6"},
  "position": [120.0, 80.0],
  "size": [220.0, 120.0],
  "label": null,
  "disabled": false,
  "version": 1,
  "notes": ""
}
```

`params` holds node configuration only. Input values arrive through edges or declared port defaults; a `core.constant` node stores its value in `params`.

### Edge

```json
{
  "id": "e_ab12cd34ef56",
  "source": "n_4e9c1559af37",
  "source_port": "value",
  "target": "n_876cda0dd89a",
  "target_port": "a"
}
```

Edges must reference existing nodes and ports; the reader validates this. Port types are resolved from the registry at load time rather than duplicated in the file.

### Frame

```json
{
  "id": "f_001122334455",
  "title": "Group",
  "position": [40.0, 40.0],
  "size": [520.0, 340.0],
  "color": "#38bdf8",
  "node_ids": ["n_4e9c1559af37"],
  "kind": "frame"
}
```

`kind` is `"frame"` for a node group or `"annotation"` for a free text note.

### Ports

Graph inputs/outputs and function parameters use `PortSpec`:

```json
{
  "name": "a",
  "type": "float",
  "description": "",
  "optional": false,
  "default": 0.0,
  "type_name": null,
  "element": "integer",
  "variadic": false
}
```

`type` is one of the built-in data type labels. `element` is only meaningful for arrays. Custom types use `type` = `"object"` with `type_name`.

## Function

```json
{
  "id": "fn_1a2b3c4d5e",
  "name": "Add",
  "description": "Adds two numbers",
  "version": 1,
  "tags": [],
  "inputs": [ { "...": "PortSpec" } ],
  "outputs": [ { "...": "PortSpec" } ],
  "graph": { "...": "Graph document" }
}
```

A function graph contains two special node types: `core.graph_input` (params `name`) and `core.graph_output` (params `name`). The callable node type is `fn.<id>`, registered into the registry when a project is loaded.

## Compatibility rules

- Unknown node types are preserved on load but cannot execute until the providing plugin is installed.
- Unknown top-level settings keys are ignored on read; unknown node params are preserved.
- Duplicate node, edge, graph or function ids are rejected with an error, never silently overwritten.
- Cycles are rejected on connect; older hand-edited files with cycles fail validation with a clear message.
- Save writes to a temporary file in the same directory and replaces the target, keeping a previous good file intact on failure.

## Autosave and recovery

`ProjectStore.autosave` writes snapshots under the app data directory keyed by project path. On startup, if a snapshot is newer than the project file mtime, the welcome screen offers recovery. Recovery data is JSON with `saved_at`, `path`, `name` and the full project document; it is stored in SQLite with the settings, recent files and plugin state.

App data location: platform application-data directory under `SYNAPSE/` (fallback `~/.synapse`).
