"""Visual debugger: breakpoints, node stepping, pause/resume/stop.

The debugger is a hook into the engine.  Because the engine runs in its own
event loop (the UI puts it in a worker thread), the control methods are safe
to call from another thread: they only touch asyncio primitives through
``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..engine.errors import ExecutionCancelled

if TYPE_CHECKING:  # avoids an engine <-> debugger import cycle
    from ..engine.executor import ExecutionRun, NodeResult


@dataclass
class TraceEntry:
    node_id: str
    graph_id: str
    node_name: str
    inputs: dict
    outputs: dict
    duration: float
    status: str
    depth: int = 0


class DebugSession:
    """Breakpoints plus step control for one run."""

    def __init__(self, *, step_into_functions: bool = False) -> None:
        self.breakpoints: set[str] = set()
        self.breakpoints_by_graph: dict[str, set[str]] = {}
        self.paused = False
        self.paused_node: str = ""
        self.paused_graph: str = ""
        self.step_mode = "run"  # run | over | into | pause
        self.stop_requested = False
        self.step_into_functions = step_into_functions
        self.history: list[TraceEntry] = []
        self.paused_inputs: dict = {}
        self._resume = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self.visited: list[str] = []
        self.finished = False
        self.error: str = ""

    # -- configuration --------------------------------------------------
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add_breakpoint(self, graph_id: str, node_id: str) -> None:
        self.breakpoints_by_graph.setdefault(graph_id, set()).add(node_id)

    def remove_breakpoint(self, graph_id: str, node_id: str) -> None:
        self.breakpoints_by_graph.get(graph_id, set()).discard(node_id)

    def toggle_breakpoint(self, graph_id: str, node_id: str) -> bool:
        active = self.breakpoints_by_graph.setdefault(graph_id, set())
        if node_id in active:
            active.discard(node_id)
            return False
        active.add(node_id)
        return True

    def has_breakpoint(self, graph_id: str, node_id: str) -> bool:
        return node_id in self.breakpoints_by_graph.get(graph_id, set())

    # -- control (thread safe) ------------------------------------------
    def request_pause(self) -> None:
        self.step_mode = "pause"

    def resume(self) -> None:
        self.step_mode = "run"
        self._wake()

    def step_over(self) -> None:
        self.step_mode = "over"
        self._wake()

    def step_into(self) -> None:
        self.step_mode = "into"
        self._wake()

    def stop(self) -> None:
        self.stop_requested = True
        self._wake()

    def _wake(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._resume.set)
        else:  # pragma: no cover - no loop bound (unit tests)
            self._resume.set()

    # -- engine hooks ---------------------------------------------------
    def _should_pause(self, run: ExecutionRun, node_id: str) -> bool:
        if self.stop_requested:
            return False
        if self.step_mode in ("pause", "over", "into"):
            return True
        return self.has_breakpoint(run.graph.id, node_id)

    async def graph_start(self, run: ExecutionRun) -> None:
        self.bind_loop(asyncio.get_running_loop())

    async def before_node(self, run: ExecutionRun, node_id: str, inputs: dict) -> None:
        if self.stop_requested:
            run.abort_reason = "cancelled"
            run.cancel_event.set()
            raise ExecutionCancelled("stopped by user")
        if not self._should_pause(run, node_id):
            return
        self._resume.clear()
        self.paused = True
        self.paused_node = node_id
        self.paused_graph = run.graph.id
        self.paused_inputs = dict(inputs)
        node = run.graph.nodes.get(node_id)
        name = node.type if node else node_id
        run.emit(
            "debug_pause",
            node_id=node_id,
            node_name=name,
            message=f"paused before {node_id}",
            data={"depth": run.depth, "inputs": {k: str(v)[:200] for k, v in inputs.items()}},
        )
        await self._resume.wait()
        self.paused = False
        self.paused_node = ""
        if self.stop_requested:
            run.abort_reason = "cancelled"
            run.cancel_event.set()
            raise ExecutionCancelled("stopped by user")
        if self.step_mode in ("over", "into"):
            self.step_mode = "pause"

    async def after_node(self, run: ExecutionRun, node_id: str, result: NodeResult) -> None:
        self.visited.append(node_id)
        self.history.append(
            TraceEntry(
                node_id=node_id,
                graph_id=run.graph.id,
                node_name=result.node_name,
                inputs=dict(result.inputs),
                outputs=dict(result.outputs),
                duration=result.duration,
                status=result.status,
                depth=run.depth,
            )
        )
        if len(self.history) > 500:
            del self.history[:100]
        if result.status == "error":
            self.error = result.error

    async def graph_finish(self, run: ExecutionRun) -> None:
        if run.depth == 0:
            self.finished = True
            self.paused = False
            run.emit("debug_finished", message="debug session finished")

    # -- inspection -----------------------------------------------------
    def trace_for(self, node_id: str) -> TraceEntry | None:
        for entry in reversed(self.history):
            if entry.node_id == node_id:
                return entry
        return None

    def elapsed(self) -> float:
        if not self.history:
            return 0.0
        return sum(e.duration for e in self.history)
