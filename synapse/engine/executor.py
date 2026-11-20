"""SYNAPSE execution engine.

Executes a :class:`~synapse.graph.model.Graph` as a dataflow program:

* dependencies are resolved from edges,
* independent nodes run concurrently (single event loop, bounded fan-out),
* every run has limits, cancellation, per-node timing and error isolation,
* pure nodes are memoised on (type, version, params, inputs),
* a debug hook can pause, step and inspect the run.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ..debugger.values import to_jsonable, value_preview
from ..functions.library import FunctionLibrary
from ..graph.model import Graph
from ..nodes.base import NodeDefinition
from ..nodes.registry import NodeRegistry, default_registry
from ..typesystem import ConversionError, coerce_value
from .context import NodeContext, SecurityPolicy
from .errors import (
    ExecutionCancelled,
    ExecutionLimitExceeded,
    NodeExecutionError,
    ControlFlowSignal,
)
from .events import EventBus, ExecutionEvent


@dataclass
class ExecutionOptions:
    max_steps: int = 20_000
    timeout: float | None = 120.0
    node_timeout: float | None = 60.0
    concurrency: int = 8
    max_recursion: int = 24
    max_loop_iterations: int = 10_000
    cache: bool = True
    fail_fast: bool = False
    record_values: bool = True
    workers: int = 4


@dataclass
class NodeResult:
    node_id: str
    node_type: str
    node_name: str
    status: str = "pending"  # ok | error | skipped | cancelled | running
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    duration: float = 0.0
    error: str = ""
    error_details: str = ""
    cached: bool = False
    order: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "type": self.node_type,
            "name": self.node_name,
            "status": self.status,
            "inputs": {k: to_jsonable(v) for k, v in self.inputs.items()},
            "outputs": {k: to_jsonable(v) for k, v in self.outputs.items()},
            "duration": self.duration,
            "error": self.error,
            "cached": self.cached,
        }


@dataclass
class ExecutionResult:
    run_id: str
    graph_id: str
    graph_name: str = ""
    status: str = "ok"  # ok | error | cancelled | timeout | invalid
    started_at: float = 0.0
    duration: float = 0.0
    nodes: dict[str, NodeResult] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    errors: list[NodeExecutionError] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    timed_out: bool = False
    limit_hit: bool = False
    validation_errors: list[str] = field(default_factory=list)
    cache_hits: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def value(self, node_id: str, port: str, default: Any = None) -> Any:
        result = self.nodes.get(node_id)
        if result is None:
            return default
        return result.outputs.get(port, default)

    def summary(self) -> str:
        ok = sum(1 for r in self.nodes.values() if r.status == "ok")
        failed = sum(1 for r in self.nodes.values() if r.status == "error")
        skipped = sum(1 for r in self.nodes.values() if r.status == "skipped")
        return (
            f"{self.status}: {ok} ok, {failed} failed, {skipped} skipped "
            f"in {self.duration:.3f}s"
        )


class NullDebugger:
    """Default debug hook: does nothing."""

    async def before_node(self, run: "ExecutionRun", node_id: str, inputs: dict) -> None:
        return None

    async def after_node(self, run: "ExecutionRun", node_id: str, result: NodeResult) -> None:
        return None

    async def graph_start(self, run: "ExecutionRun") -> None:
        return None

    async def graph_finish(self, run: "ExecutionRun") -> None:
        return None


def _stable_key(definition: NodeDefinition, params: dict, inputs: dict) -> str | None:
    try:
        payload = json.dumps(
            {
                "type": definition.type_id,
                "version": definition.version,
                "params": to_jsonable(params),
                "inputs": to_jsonable(inputs),
            },
            sort_keys=True,
            default=repr,
        )
    except Exception:  # pragma: no cover - defensive
        return None
    return payload


class ExecutionRun:
    """State of a single graph execution (including nested function calls)."""

    def __init__(
        self,
        executor: "Executor",
        graph: Graph,
        *,
        inputs: dict | None = None,
        options: ExecutionOptions | None = None,
        debugger: Any = None,
        scope: dict | None = None,
        depth: int = 0,
        parent: "ExecutionRun | None" = None,
        run_id: str | None = None,
    ) -> None:
        self.executor = executor
        self.graph = graph
        self.graph_inputs = dict(inputs or {})
        self.options = options or ExecutionOptions()
        self.debugger = debugger or NullDebugger()
        self.scope = scope if scope is not None else {}
        self.depth = depth
        self.parent = parent
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.cancel_event = asyncio.Event()
        self.event_bus = EventBus()
        self.security: SecurityPolicy = executor.security.with_root(executor.project_dir) \
            if executor.project_dir else executor.security
        self.services = executor.services
        self.project_dir = executor.project_dir
        self.loop = asyncio.get_event_loop()
        self.results: dict[str, NodeResult] = {}
        self.outputs: dict[str, dict] = {}
        self.inputs: dict[str, dict] = {}
        self.errors: list[NodeExecutionError] = []
        self.steps = 0
        self.abort_reason: str | None = None
        self.timed_out = False
        self.limit_hit = False
        self.control_signal: ControlFlowSignal | None = None
        self._tasks: dict[str, asyncio.Task] = {}
        self.result = ExecutionResult(run_id=self.run_id, graph_id=graph.id, graph_name=graph.name)
        self.executor_ref = executor

    # -- services used by nodes -----------------------------------------
    def emit(self, kind: str, **payload: Any) -> None:
        event = ExecutionEvent(
            kind=kind,
            run_id=self.run_id,
            graph_id=self.graph.id,
            **payload,
        )
        self.executor.emit_event(event)

    def emit_log(self, node_id: str, node_name: str, message: str, level: str = "info") -> None:
        self.emit(
            "log",
            node_id=node_id,
            node_name=node_name,
            message=message,
            level=level,
        )

    def check_limits(self) -> None:
        if self.steps > self.options.max_steps:
            self.limit_hit = True
            raise ExecutionLimitExceeded(
                f"step limit of {self.options.max_steps} reached"
            )

    def tick(self) -> None:
        self.steps += 1
        self.check_limits()

    async def call_function(self, function_id: str, inputs: dict, *, parent_ctx=None) -> dict:
        return await self.executor.run_function_call(self, function_id, inputs)

    def cancel(self) -> None:
        self.abort_reason = self.abort_reason or "cancelled"
        self.cancel_event.set()

    # -- execution ------------------------------------------------------
    async def execute(self) -> ExecutionResult:
        started = time.perf_counter()
        self.result.started_at = started
        problems = self.graph.validate()
        if problems:
            self.result.status = "invalid"
            self.result.validation_errors = problems
            self.result.duration = time.perf_counter() - started
            self.emit("graph_error", message="; ".join(problems), level="error")
            return self.result

        try:
            order = self.graph.topological_order()
        except Exception as exc:
            self.result.status = "invalid"
            self.result.validation_errors = [str(exc)]
            self.result.duration = time.perf_counter() - started
            return self.result
        self.result.order = order
        self.emit("graph_start", data={"nodes": len(order)})
        await self.debugger.graph_start(self)

        deps: dict[str, set[str]] = {node_id: set() for node_id in self.graph.nodes}
        for edge in self.graph.edges:
            if edge.target in deps and edge.source in deps:
                deps[edge.target].add(edge.source)

        try:
            self._tasks = {
                node_id: asyncio.create_task(
                    self._node_task(node_id, deps[node_id]), name=f"synapse:{node_id}"
                )
                for node_id in order
            }
            watcher = asyncio.create_task(self._watch_cancel(), name="synapse:cancel")
            gather = asyncio.gather(*self._tasks.values(), return_exceptions=True)
            timeout = self.options.timeout
            try:
                if timeout:
                    await asyncio.wait_for(gather, timeout=timeout)
                else:
                    await gather
            except asyncio.TimeoutError:
                self.timed_out = True
                self.abort_reason = "timeout"
                self.cancel_event.set()
                for task in self._tasks.values():
                    task.cancel()
                await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            finally:
                watcher.cancel()
        except ExecutionCancelled:
            self.cancel()
        except Exception as exc:  # pragma: no cover - defensive
            self.errors.append(
                NodeExecutionError(f"engine failure: {exc}", details=traceback.format_exc())
            )
        finally:
            self.result.duration = time.perf_counter() - started
            self._finalise()
            await self.debugger.graph_finish(self)
            self.emit("graph_finish", duration=self.result.duration,
                      message=self.result.summary())
        return self.result

    async def _watch_cancel(self) -> None:
        await self.cancel_event.wait()
        for task in self._tasks.values():
            if not task.done():
                task.cancel()

    async def _node_task(self, node_id: str, dependencies: set[str]) -> None:
        if dependencies:
            await asyncio.gather(
                *(self._tasks[d] for d in dependencies if d in self._tasks),
                return_exceptions=True,
            )
        node = self.graph.nodes[node_id]
        definition = self.executor.registry.get(node.type)
        base = NodeResult(
            node_id=node_id,
            node_type=node.type,
            node_name=definition.name if definition else node.type,
            order=len(self.results),
        )
        self.results[node_id] = base
        if definition is None:
            base.status = "error"
            base.error = f"unknown node type '{node.type}'"
            self.errors.append(NodeExecutionError(base.error, node_id=node_id, node_type=node.type))
            self.emit("node_error", node_id=node_id, node_name=node.type, message=base.error)
            return

        if self.cancel_event.is_set() or self.abort_reason:
            base.status = "cancelled"
            return
        if node.disabled:
            base.status = "skipped"
            base.outputs = {p.name: None for p in definition.resolve_outputs(self.graph, node)}
            self.outputs[node_id] = base.outputs
            self.emit("node_skipped", node_id=node_id, node_name=definition.name,
                      message="node is disabled")
            return
        blocked = [
            d for d in dependencies
            if self.results.get(d) is not None and self.results[d].status != "ok"
        ]
        if blocked:
            base.status = "skipped"
            base.error = "upstream node failed: " + ", ".join(sorted(blocked))
            self.emit("node_skipped", node_id=node_id, node_name=definition.name,
                      message=base.error)
            return

        try:
            inputs = self._collect_inputs(node, definition)
        except (ConversionError, KeyError, ValueError) as exc:
            self._fail(node_id, base, definition, exc, traceback.format_exc())
            return

        base.inputs = inputs
        base.status = "running"
        self.inputs[node_id] = inputs
        self.emit(
            "node_start",
            node_id=node_id,
            node_name=definition.name,
            data={k: value_preview(v) for k, v in inputs.items()},
        )
        started = time.perf_counter()
        try:
            await self.debugger.before_node(self, node_id, inputs)
            if self.cancel_event.is_set() or self.abort_reason:
                raise ExecutionCancelled("execution cancelled")

            cache_key = None
            if self.options.cache and definition.pure:
                cache_key = _stable_key(definition, node.params, inputs)
                cached = self.executor.cache_get(cache_key) if cache_key else None
                if cached is not None:
                    base.outputs = dict(cached)
                    base.status = "ok"
                    base.cached = True
                    base.duration = 0.0
                    self.outputs[node_id] = base.outputs
                    self.result.cache_hits += 1
                    self.emit("node_finish", node_id=node_id, node_name=definition.name,
                              duration=0.0, data={"cached": True})
                    await self.debugger.after_node(self, node_id, base)
                    return

            self.tick()
            ctx = NodeContext(self, node, definition)
            invoke = definition.invoke(ctx, inputs, node.params)
            node_timeout = self.options.node_timeout
            if node_timeout:
                raw = await asyncio.wait_for(invoke, timeout=node_timeout)
            else:
                raw = await invoke
            outputs = self._collect_outputs(node, definition, raw)
            base.outputs = outputs
            base.status = "ok"
            base.duration = time.perf_counter() - started
            self.outputs[node_id] = outputs
            if cache_key and definition.pure:
                self.executor.cache_put(cache_key, outputs)
            self.emit(
                "node_finish",
                node_id=node_id,
                node_name=definition.name,
                duration=base.duration,
                data={k: value_preview(v) for k, v in outputs.items()},
            )
            for port, value in outputs.items():
                if self.options.record_values:
                    self.emit("node_output", node_id=node_id, node_name=definition.name,
                              port=port, value=value)
            await self.debugger.after_node(self, node_id, base)
        except asyncio.CancelledError:
            base.status = "cancelled"
            base.duration = time.perf_counter() - started
            raise
        except ExecutionCancelled as exc:
            base.status = "cancelled"
            base.error = str(exc)
            base.duration = time.perf_counter() - started
        except ControlFlowSignal as signal:
            base.status = "skipped"
            base.duration = time.perf_counter() - started
            self.control_signal = signal
            self.abort_reason = "control"
            self.cancel_event.set()
            self.emit(
                "node_skipped",
                node_id=node_id,
                node_name=definition.name,
                message=f"{signal.kind} signal",
            )
        except asyncio.TimeoutError:
            self._fail(
                node_id, base, definition,
                ExecutionLimitExceeded(
                    f"node timed out after {self.options.node_timeout:g}s"
                ),
                "",
                started=started,
            )
            self.limit_hit = True
        except Exception as exc:
            self._fail(node_id, base, definition, exc, traceback.format_exc(), started=started)
            if self.options.fail_fast:
                # Stop scheduling, but report the run as failed rather than cancelled.
                self.abort_reason = self.abort_reason or "fail_fast"
                self.cancel_event.set()

    def _fail(self, node_id, base, definition, exc, details, *, started=None) -> None:
        base.status = "error"
        base.error = f"{type(exc).__name__}: {exc}"
        base.error_details = details or ""
        if started:
            base.duration = time.perf_counter() - started
        error = NodeExecutionError(
            str(exc),
            node_id=node_id,
            node_name=definition.name,
            node_type=definition.type_id,
            details=details or "",
        )
        self.errors.append(error)
        self.emit(
            "node_error",
            node_id=node_id,
            node_name=definition.name,
            message=base.error,
            duration=base.duration,
            level="error",
        )

    def _collect_inputs(self, node, definition: NodeDefinition) -> dict:
        values: dict[str, Any] = {}
        for port in definition.resolve_inputs(self.graph, node):
            edge = self.graph.edge_into(node.id, port.name)
            if edge is not None:
                upstream = self.outputs.get(edge.source, {})
                if base := self.results.get(edge.source):
                    if base.status != "ok":
                        raise ValueError(
                            f"upstream node '{edge.source}' did not produce a value"
                        )
                value = upstream.get(edge.source_port)
                source_def = self.executor.registry.get(self.graph.nodes[edge.source].type)
                source_port = (
                    source_def.port(edge.source_port, output=True)
                    if source_def else None
                )
                if value is None and source_port is not None and source_port.default is not None:
                    value = source_port.default
            elif port.name in node.params:
                value = node.params[port.name]
            else:
                value = port.default
            if value is None and not port.optional and port.default is None:
                raise ValueError(f"required input '{port.name}' has no value")
            if value is not None:
                value = coerce_value(value, port.spec, port=port.name)
            values[port.name] = value
        return values

    def _collect_outputs(self, node, definition: NodeDefinition, raw: dict) -> dict:
        outputs: dict[str, Any] = {}
        for port in definition.resolve_outputs(self.graph, node):
            value = raw.get(port.name)
            if value is not None:
                value = coerce_value(value, port.spec, port=port.name)
            outputs[port.name] = value
        return outputs

    def _finalise(self) -> None:
        result = self.result
        result.nodes = dict(self.results)
        result.errors = list(self.errors)
        result.cancelled = bool(self.abort_reason == "cancelled")
        result.timed_out = self.timed_out
        result.limit_hit = self.limit_hit
        outputs: dict[str, Any] = {}
        for node_id, node in self.graph.nodes.items():
            if node.type != "core.graph_output":
                continue
            name = str(node.params.get("name") or "output")
            port = self.graph.edge_into(node_id, "value")
            if port is not None:
                source_result = self.results.get(port.source)
                if source_result is None or source_result.status != "ok":
                    continue
                value = self.outputs.get(port.source, {}).get(port.source_port)
            elif "value" in node.params:
                value = node.params["value"]
            else:
                value = None
            outputs[name] = value
        result.outputs = outputs
        for name, spec in ((p.name, p) for p in self.graph.outputs):
            if name not in outputs:
                outputs[name] = None

        if self.timed_out:
            result.status = "timeout"
        elif self.abort_reason == "control":
            result.status = "ok"
        elif self.abort_reason == "cancelled":
            result.status = "cancelled"
        elif self.abort_reason == "fail_fast":
            result.status = "error"
        elif self.errors:
            result.status = "error"
        else:
            result.status = "ok"
        result.duration = result.duration or 0.0


class Executor:
    """Runs graphs; reusable across runs so the execution cache survives."""

    def __init__(
        self,
        registry: NodeRegistry | None = None,
        functions: FunctionLibrary | None = None,
        *,
        security: SecurityPolicy | None = None,
        services: dict | None = None,
        project_dir: str | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.functions = functions or FunctionLibrary(self.registry)
        self.security = security or SecurityPolicy()
        self.services = dict(services or {})
        self.project_dir = project_dir
        self.cache: dict[str, dict] = {}
        self._cache_order: list[str] = []
        self._cache_lock = threading.Lock()
        self.max_cache_entries = 256
        self._sinks: list[Callable[[ExecutionEvent], None]] = []
        self._workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="synapse-worker")
        self.last_result: ExecutionResult | None = None

    # -- observers ------------------------------------------------------
    def add_sink(self, sink: Callable[[ExecutionEvent], None]) -> None:
        self._sinks.append(sink)

    def remove_sink(self, sink: Callable[[ExecutionEvent], None]) -> None:
        if sink in self._sinks:
            self._sinks.remove(sink)

    def emit_event(self, event: ExecutionEvent) -> None:
        for sink in list(self._sinks):
            try:
                sink(event)
            except Exception:  # pragma: no cover - never break a run for a listener
                pass

    # -- cache ----------------------------------------------------------
    def cache_get(self, key: str) -> dict | None:
        with self._cache_lock:
            value = self.cache.get(key)
            return dict(value) if value is not None else None

    def cache_put(self, key: str, outputs: dict) -> None:
        with self._cache_lock:
            if key not in self.cache:
                self._cache_order.append(key)
            self.cache[key] = dict(outputs)
            while len(self._cache_order) > self.max_cache_entries:
                oldest = self._cache_order.pop(0)
                self.cache.pop(oldest, None)

    def clear_cache(self) -> None:
        with self._cache_lock:
            self.cache.clear()
            self._cache_order.clear()

    # -- runs -----------------------------------------------------------
    def make_run(
        self,
        graph: Graph,
        *,
        inputs: dict | None = None,
        options: ExecutionOptions | None = None,
        debugger: Any = None,
        scope: dict | None = None,
        depth: int = 0,
    ) -> ExecutionRun:
        return ExecutionRun(
            self,
            graph,
            inputs=inputs,
            options=options,
            debugger=debugger,
            scope=scope,
            depth=depth,
        )

    async def run(
        self,
        graph: Graph,
        *,
        inputs: dict | None = None,
        options: ExecutionOptions | None = None,
        debugger: Any = None,
        scope: dict | None = None,
    ) -> ExecutionResult:
        run = self.make_run(
            graph, inputs=inputs, options=options, debugger=debugger, scope=scope
        )
        result = await run.execute()
        self.last_result = result
        return result

    async def run_function_call(self, run: ExecutionRun, function_id: str, inputs: dict) -> dict:
        function = self.functions.get(function_id)
        if function is None:
            raise NodeExecutionError(
                f"function '{function_id}' is not available in this project"
            )
        if run.depth + 1 > run.options.max_recursion:
            raise ExecutionLimitExceeded(
                f"maximum function recursion depth ({run.options.max_recursion}) reached"
            )
        child = ExecutionRun(
            self,
            function.graph,
            inputs=inputs,
            options=run.options,
            debugger=NullDebugger(),
            scope={},
            depth=run.depth + 1,
            parent=run,
            run_id=run.run_id,
        )
        child.result.graph_name = function.name
        await child.execute()
        if child.control_signal is not None:
            raise child.control_signal
        if child.errors:
            first = child.errors[0]
            raise NodeExecutionError(
                f"function '{function.name}' failed: {first}",
                node_id=first.node_id,
                node_type=first.node_type,
                details=first.details,
            )
        if child.result.status in ("cancelled", "timeout"):
            raise ExecutionCancelled(f"function '{function.name}' was {child.result.status}")
        outputs = dict(child.result.outputs)
        for spec in function.outputs:
            if spec.name not in outputs:
                outputs[spec.name] = None
            if outputs[spec.name] is None and not spec.optional and spec.default is not None:
                outputs[spec.name] = spec.default
        return outputs

    def submit(self, fn, /, *args, **kwargs):
        """Queue blocking work on the engine's worker pool."""
        return self._workers.submit(fn, *args, **kwargs)

    def shutdown(self) -> None:
        self._workers.shutdown(wait=False, cancel_futures=True)
