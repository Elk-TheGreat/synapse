# Security model

SYNAPSE runs code that comes from several trust levels: built-in nodes, project files, user scripts, and third-party plugins. This document states what the application enforces and, just as importantly, what it does not.

## Trust levels

| Source | Trust | Runs where |
| --- | --- | --- |
| Built-in nodes | Trusted, part of the application | In-process |
| Node parameters in a project file | Data | Never executed as code except in script/command nodes |
| User Python scripts | Untrusted | Separate `python -I` subprocess |
| `runtime: "python"` plugins | Untrusted but in-process after explicit install | Host process |
| `runtime: "script"` plugins | Untrusted | Separate `python -I` subprocess per node |
| Imported graphs | Data | Validated; unknown node types cannot run |

Opening a project never executes it. Nothing runs until the user presses Run or Debug.

## Runtime policy (guard rails)

`SecurityPolicy` is built from the project settings and passed to every node through `NodeContext`. It is enforced by the built-in nodes themselves:

- **File roots** — all file node paths are resolved and must stay inside `file_roots`. A project with no roots cannot use file nodes at all. Writes additionally require `allow_file_write`.
- **Network** — `allow_network=False` blocks HTTP, WebSocket, TCP and download nodes. `allowed_hosts` restricts destinations to exact hosts or their subdomains.
- **Process execution** — disabled unless `allow_process=True`; this covers the process/system-command node.
- **Scripts** — disabled unless `allow_scripts=True`, with a per-script timeout and an import allow-list.
- **Size limits** — file reads are capped (`max_file_bytes`, default 64 MB) and downloads are capped (`max_download_bytes`, default 128 MB).
- **Host allow-list** is checked after URL parsing, including redirects performed through the same helper.

These are application-level guard rails against mistakes and untrusted project content. They are **not an OS sandbox**: a Python plugin or a script that escapes its allow-list runs with the user's privileges.

## Python scripts

`script.python` and `script.python_file` run code in a child interpreter started as `python -I`:

- No inherited `PYTHONPATH`, user site-packages or `sitecustomize`.
- Only JSON-serialisable inputs and results cross the process boundary.
- A hard wall-clock timeout; on expiry the child is killed and the node fails with a clear error.
- `open`, `exec`, `eval`, `compile`, `input`, `breakpoint` and similar builtins are removed inside the worker.
- Imports are restricted to a small standard-library allow-list plus modules the node explicitly lists. `allow_all_imports` disables that check and is off by default.
- Scripts run with the project directory as working directory, not the application directory.

Residual risks: the child still runs on the host. A determined script can use permitted modules to read process information or consume CPU until the timeout. Run untrusted projects in a container or a separate OS account if that matters to you.

Imported scripts are never executed automatically; they run only when their node executes.

## Plugins

- Installing a plugin is an explicit action; discovery does not import plugin code until "load enabled" runs, and only enabled plugins are loaded.
- Python plugins receive `PluginAPI`, not the host registry or the filesystem helpers directly. Type ids are namespaced, built-in ids cannot be overwritten, and declared permissions (`files`, `network`, `process`, `scripts`) gate the convenience helpers.
- Declared permissions are a disclosure mechanism, not a jail. Python plugins are ordinary Python in the host process. Install only code you trust, and read `plugin.json`.
- Script-runtime plugins inherit the script sandbox described above.
- A broken plugin cannot prevent startup: load errors are contained, reported to the Plugins dialog and skipped.
- Plugins ship with a version and a `api_version`; incompatible or duplicate plugins are refused.
- Bundled plugins cannot be removed, only disabled.

## AI and network nodes

AI nodes speak the OpenAI-compatible HTTP protocol. API keys are read from environment variables only; they are never written into project files, logs, execution history or exported code. Prompts, inputs and results may leave the machine when you run them — that is the point of the node, and it is the user's decision.

## Exported programs

Exported Python contains the graph JSON, function definitions and node parameters. Treat an exported file as source code: it may contain file paths, prompts, URLs or data embedded in constants. Do not export projects containing secrets in constants.

## Session data

Settings, recent projects, plugin enablement and recovery snapshots live in a SQLite database in the platform application-data directory. Project files themselves are written where the user chooses. No telemetry is collected.

## Reporting

This is an open-source project; report security issues privately to the maintainers before opening a public issue.
