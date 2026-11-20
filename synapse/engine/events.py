"""Execution events and a tiny in-process event bus."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionEvent:
    """One observable step of a run (consumed by the UI and the debugger)."""

    kind: str
    run_id: str = ""
    graph_id: str = ""
    node_id: str = ""
    node_name: str = ""
    port: str = ""
    value: Any = None
    duration: float = 0.0
    message: str = ""
    level: str = "info"
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        from ..debugger.values import to_jsonable

        return {
            "kind": self.kind,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "port": self.port,
            "value": to_jsonable(self.value) if self.value is not None else None,
            "duration": self.duration,
            "message": self.message,
            "level": self.level,
            "data": self.data,
        }


class EventBus:
    """Named events that nodes can emit and await inside one run."""

    def __init__(self) -> None:
        self._waiters: dict[str, list[asyncio.Future]] = {}
        self.history: list[tuple[str, Any]] = []

    def emit(self, name: str, payload: Any = None) -> None:
        self.history.append((name, payload))
        for future in self._waiters.pop(name, []):
            if not future.done():
                future.set_result(payload)

    async def wait(self, name: str, timeout: float | None = None) -> Any:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._waiters.setdefault(name, []).append(future)
        if timeout is None:
            return await future
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            waiters = self._waiters.get(name, [])
            if future in waiters:
                waiters.remove(future)
            raise TimeoutError(f"no '{name}' event arrived within {timeout:g}s")
