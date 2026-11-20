# Architecture

SYNAPSE separates a Qt-free program model from the desktop shell. The engine, graph, type system, compiler, project format and extension API can be used headlessly (the test suite and exported programs do exactly that).

## Layers

```
application/   PySide6 shell, canvas, panels, dialogs, themes, run controller
      │  uses
engine/        async dataflow executor, contexts, security policy, events
debugger/      tracing session layered on engine events
compiler/      shared IR + Python/JSON generation
      │  reads
graph/         nodes, edges, frames, ports, cycles, serialisation
nodes/         NodeDefinition/ParamSpec, registry, built-in library
typesystem/    DataType, TypeSpec, PortSpec, conversion, custom types
project/       versioned project document, templates, store, SQLite database
functions/     sub-graph functions and structural extraction
scripting/     isolated interpreter + pluggable language engines
extensions/    plugin manifests, API, discovery, install/remove
```

Dependencies point downward only. `graph` never imports Qt or node implementations; it resolves node types through an injected `NodeRegistry`. That keeps the model testable and allows performance-critical pieces (executor scheduling, graph algorithms) to be replaced by a Rust extension behind the same interfaces.

## Graph model

- `NodeInstance` holds `id`, `type`, `params`, position, size, label, disabled flag, notes and schema version.
- `Edge` is a directed connection `(source, source_port) → (target, target_port)`.
- `Frame` groups nodes visually or acts as a free annotation.
- `Graph` owns nodes, edges, frames, graph variables plus declared graph inputs/outputs. It validates port existence, type compatibility, one-edge-per-input and rejects cycles at connection time.
- Inputs not connected fall back to the node's port default; graph inputs are supplied by the caller and graph outputs are collected by `core.graph_output` nodes.

Execution is dataflow, not control-flow dominance: every node becomes ready when all required inputs have values. Conditions and loops are modelled explicitly (`logic.if`, `logic.switch`, loop nodes executing a body function) so the graph never needs hidden control edges.

## Type system

`DataType` is a closed enum of built-ins (`boolean`, `integer`, `float`, `string`, `bytes`, `array`, `dictionary`, `image`, `audio`, `video`, `file`, `object`, `any`). `TypeSpec` adds an optional custom type name and an array element type. `PortSpec` declares name, type, optionality, default and variadic flag.

Compatibility is directional (`is_compatible(source, target)`): `any` matches everything, int is accepted by float ports, arrays may declare element types. `coerce_value` performs explicit, safe conversion for configured values and connection adaptation; failures raise `ConversionError` instead of producing silently wrong data. Media values are wrappers (`Image`, `Audio`, `Video`, `FileRef`) so they stay distinct from raw bytes and survive serialisation boundaries.

## Node definitions

Every node is a `NodeDefinition` with `type_id`, display name, category, description, inputs, outputs, `ParamSpec` configuration, version, `pure` flag, keywords and an async `execute(ctx, inputs, params)` function. Registration is declarative (`@node(...)`) and the registry supports lookup, category grouping, search, listener notifications and source-scoped unregistering (used by plugins and functions).

`pure=True` nodes can be cached by the executor when inputs and params are unchanged. `blocking=True` nodes are submitted to a worker pool through `ctx.run_blocking`, keeping the event loop responsive.

## Execution engine

`Executor.run(graph, inputs=..., options=..., debugger=...)` creates an `ExecutionRun`:

1. Build an in-degree map, seed graph inputs and already-satisfied ports.
2. Schedule every ready node as an asyncio task, up to `concurrency`.
3. Await completion in waves; each result unlocks dependents.
4. Record `NodeResult` (outputs, duration, status, error), emit events and feed the debugger.
5. Stop on failure (optional fail-fast), cancellation, timeout, step limit, node timeout, recursion limit or loop-iteration limit.

Loops are bounded by `max_loop_iterations` and the overall run by `max_steps`, so a bad graph cannot freeze the UI. Cancellation is cooperative through asyncio and also cancels queued work. Blocking calls use a worker pool via `asyncio.wrap_future`; caches are per-executor and thread-safe. Every run cleans up tasks, worker futures and temporary state.

Engine events (`node_started`, `node_finished`, `node_failed`, `run_finished`, …) are re-emitted as Qt signals through queued connections so the UI can highlight active nodes and wires without touching engine state.

## Debugger

`DebugSession` subscribes to engine events. It records a bounded trace (`TraceEntry`: node, inputs, outputs, duration, status, depth), manages breakpoints per graph, and can pause before a node runs, step one node, or resume. Pausing is implemented with an asyncio future resolved from the UI thread via `loop.call_soon_threadsafe`; the engine remains the single owner of execution state.

## Functions and the IR

`extract_function` is a structural transformation: selected nodes are copied into a new `FunctionDef` graph, external incoming edges become graph inputs (`core.graph_input` nodes), external outgoing edges become graph outputs, and caller-side reconnection points are returned. A generated `fn.<id>` node type lets any graph call the function.

`build_ir` converts a graph into `CompiledGraph`/`IRNode`/`IRInput`, resolving port provenance and listing unsupported nodes. The same IR powers JSON export and `generate_python`, which writes a standalone program embedding the graph JSON, the function library and the SYNAPSE runtime bootstrap. Unsupported constructs are enumerated in the generated header; no translator claims semantics it cannot preserve.

## Threading model

- UI thread: Qt only.
- Run thread: owns an asyncio event loop for the active execution.
- Worker threads: blocking node operations and script subprocesses.
- Communication: engine events → Qt signals (queued); debugger commands → loop callbacks.

## Extension points

- `NodeRegistry` — add node definitions from Python or plugins.
- `register_engine` — add JavaScript/Rust/other script runtimes implementing `run(source, inputs, params, options)`.
- `PluginManager` — discover, install, enable and load packages.
- `SecurityPolicy` — per-project permissions and path roots.
- `CustomType` registration for domain-specific port types.

## Why Python first

The model, IR and node contracts are language-neutral. Rust can later implement the scheduler and graph algorithms behind `Executor`/`Graph` APIs without changing project files, node libraries or the UI, because neither depends on Python implementation details.
