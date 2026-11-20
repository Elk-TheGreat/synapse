"""Bridge between the Qt UI and the asyncio execution engine.

Runs execute in a dedicated thread with their own event loop so the interface
never blocks.  Engine events are re-emitted as Qt signals, which Qt delivers to
the UI thread through queued connections.
"""

from __future__ import annotations

import asyncio
import threading
import traceback

from PySide6.QtCore import QObject, Signal

from ..debugger.session import DebugSession, TraceEntry
from ..engine.context import SecurityPolicy
from ..engine.executor import ExecutionOptions, ExecutionResult, Executor
from ..graph.model import Graph
from ..nodes.registry import NodeRegistry


class _TracingDebugger(DebugSession):
    def __init__(self, controller: "RunController") -> None:
        super().__init__()
        self._controller = controller

    async def after_node(self, run, node_id, result) -> None:
        await super().after_node(run, node_id, result)
        entry = self.history[-1] if self.history else None
        if entry is not None:
            self._controller.node_traced.emit(entry)


class RunController(QObject):
    started = Signal(str, bool)
    event = Signal(object)
    node_traced = Signal(object)
    paused = Signal(str, str, dict)
    resumed = Signal()
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._run = None
        self._debugger: DebugSession | None = None
        self._lock = threading.Lock()
        self.debug_active = False

    # -- state ----------------------------------------------------------
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def debugger(self) -> DebugSession | None:
        return self._debugger

    # -- execution ------------------------------------------------------
    def start(
        self,
        executor: Executor,
        graph: Graph,
        *,
        inputs: dict | None = None,
        options: ExecutionOptions | None = None,
        debug: bool = False,
        breakpoints: dict[str, set[str]] | None = None,
    ) -> bool:
        if self.is_running():
            return False
        snapshot = Graph.from_dict(graph.to_dict(), registry=executor.registry)
        snapshot.name = graph.name
        self.debug_active = debug
        self._thread = threading.Thread(
            target=self._worker,
            args=(executor, snapshot, dict(inputs or {}), options, debug, dict(breakpoints or {})),
            name="synapse-run",
            daemon=True,
        )
        self.started.emit(graph.name, debug)
        self._thread.start()
        return True

    def _worker(
        self,
        executor: Executor,
        graph: Graph,
        inputs: dict,
        options,
        debug: bool,
        breakpoints: dict[str, set[str]],
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        debugger = _TracingDebugger(self) if debug else None
        if debugger is not None:
            for graph_id, node_ids in breakpoints.items():
                for node_id in node_ids:
                    debugger.add_breakpoint(graph_id, node_id)
        self._debugger = debugger
        executor.add_sink(self._emit)
        try:
            run = executor.make_run(
                graph, inputs=inputs, options=options, debugger=debugger
            )
            with self._lock:
                self._run = run
            result = loop.run_until_complete(run.execute())
            self.finished.emit(result)
        except BaseException as exc:  # never lose a crash in the worker
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        finally:
            executor.remove_sink(self._emit)
            try:
                executor.shutdown()
            except Exception:
                pass
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            with self._lock:
                self._loop = None
                self._run = None
            self._debugger = None
            self._thread = None
            self.debug_active = False

    def _emit(self, event) -> None:
        self.event.emit(event)
        if event.kind == "debug_pause":
            data = event.data or {}
            self.paused.emit(event.node_id, event.node_name, dict(data.get("inputs") or {}))

    # -- control --------------------------------------------------------
    def cancel(self) -> None:
        with self._lock:
            run = self._run
            loop = self._loop
        if run is None or loop is None:
            return
        try:
            loop.call_soon_threadsafe(run.cancel)
        except RuntimeError:
            pass

    def pause(self) -> None:
        if self._debugger is not None:
            self._debugger.request_pause()

    def resume(self) -> None:
        if self._debugger is not None:
            self._debugger.resume()
            self.resumed.emit()

    def step(self) -> None:
        if self._debugger is not None:
            self._debugger.step_over()
            self.resumed.emit()

    def step_into(self) -> None:
        if self._debugger is not None:
            self._debugger.step_into()
            self.resumed.emit()

    def stop(self) -> None:
        if self._debugger is not None:
            self._debugger.stop()
        self.cancel()


def make_executor(registry: NodeRegistry, library, settings, project_dir: str | None) -> Executor:
    security = SecurityPolicy(
        file_roots=[str(r) for r in settings.file_roots],
        allow_write=bool(settings.allow_file_write),
        allow_network=bool(settings.allow_network),
        allow_process=bool(settings.allow_process),
        allow_scripts=bool(settings.allow_scripts),
        allowed_hosts=tuple(str(h) for h in settings.allowed_hosts if h),
        script_timeout=max(1.0, float(settings.node_timeout)),
        network_timeout=max(1.0, min(float(settings.node_timeout), 60.0)),
    )
    return Executor(
        registry,
        library,
        security=security,
        project_dir=project_dir,
    )


def options_from_settings(settings) -> ExecutionOptions:
    return ExecutionOptions(
        max_steps=int(settings.max_steps),
        timeout=float(settings.run_timeout),
        node_timeout=float(settings.node_timeout),
        concurrency=max(1, int(settings.concurrency)),
    )
