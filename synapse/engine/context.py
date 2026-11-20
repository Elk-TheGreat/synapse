"""Runtime context handed to every node, plus the security policy.

Nodes never touch the host directly: file access goes through
``SecurityPolicy.resolve_path`` and network/process access is gated by flags.
The policy is a guard rail, not an OS sandbox - see documentation/SECURITY.md.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import ExecutionCancelled, SecurityError


DEFAULT_MAX_FILE_BYTES = 64 * 1024 * 1024


@dataclass
class SecurityPolicy:
    """What a run is allowed to touch."""

    file_roots: list[str] = field(default_factory=list)
    allow_read: bool = True
    allow_write: bool = True
    allow_network: bool = True
    allow_process: bool = False
    allow_scripts: bool = True
    script_timeout: float = 10.0
    script_allowed_imports: tuple[str, ...] = (
        "math", "json", "re", "statistics", "random", "datetime", "itertools",
        "functools", "collections", "decimal", "fractions", "textwrap", "string",
        "hashlib", "base64", "uuid", "csv", "heapq", "bisect", "typing",
    )
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    network_timeout: float = 20.0
    allowed_hosts: tuple[str, ...] = ()
    max_download_bytes: int = 128 * 1024 * 1024

    def with_root(self, root: str) -> "SecurityPolicy":
        roots = list(self.file_roots)
        resolved = str(Path(root).expanduser().resolve())
        if resolved not in roots:
            roots.append(resolved)
        return SecurityPolicy(**{**self.__dict__, "file_roots": roots})

    def describe(self) -> dict[str, Any]:
        return {
            "file_roots": list(self.file_roots),
            "allow_read": self.allow_read,
            "allow_write": self.allow_write,
            "allow_network": self.allow_network,
            "allow_process": self.allow_process,
            "allow_scripts": self.allow_scripts,
            "allowed_hosts": list(self.allowed_hosts),
        }

    # -- checks ---------------------------------------------------------
    def check_network(self, url: str = "") -> None:
        if not self.allow_network:
            raise SecurityError(
                "network access is disabled for this project (Settings > Security)"
            )
        if self.allowed_hosts and url:
            from urllib.parse import urlparse

            host = (urlparse(url).hostname or "").lower()
            allowed = [h.lower() for h in self.allowed_hosts]
            if not any(host == h or host.endswith("." + h) for h in allowed):
                raise SecurityError(
                    f"host '{host}' is not in the project's allowed host list"
                )

    def check_process(self) -> None:
        if not self.allow_process:
            raise SecurityError(
                "process execution is disabled for this project (Settings > Security)"
            )

    def check_scripts(self) -> None:
        if not self.allow_scripts:
            raise SecurityError("script nodes are disabled for this project")

    def resolve_path(self, path: str, *, write: bool = False) -> str:
        """Resolve ``path`` and ensure it stays inside an allowed root."""
        if not path or not isinstance(path, (str, os.PathLike)):
            raise SecurityError("a file path is required")
        if write and not self.allow_write:
            raise SecurityError("file writes are disabled for this project")
        if not write and not self.allow_read:
            raise SecurityError("file reads are disabled for this project")
        raw = os.fspath(path)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute() and self.file_roots:
            candidate = Path(self.file_roots[0]) / candidate
        resolved = candidate.resolve(strict=False)
        if not self.file_roots:
            raise SecurityError(
                "no file roots are configured; grant a project folder in Settings > Security"
            )
        for root in self.file_roots:
            try:
                resolved.relative_to(Path(root).resolve())
                return str(resolved)
            except ValueError:
                continue
        raise SecurityError(
            f"path '{resolved}' is outside the project's allowed folders "
            f"({', '.join(self.file_roots)})"
        )


class NodeContext:
    """Per-node runtime handle."""

    def __init__(self, run: Any, node: Any, definition: Any) -> None:
        self._run = run
        self.node = node
        self.definition = definition

    # -- identity -------------------------------------------------------
    @property
    def node_id(self) -> str:
        return self.node.id

    @property
    def graph(self) -> Any:
        return self._run.graph

    @property
    def graph_id(self) -> str:
        return self._run.graph.id

    @property
    def variables(self) -> dict:
        return self._run.scope

    @property
    def security(self) -> SecurityPolicy:
        return self._run.security

    @property
    def services(self) -> dict:
        return self._run.services

    @property
    def project_dir(self) -> str | None:
        return self._run.project_dir

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._run.loop

    @property
    def run_id(self) -> str:
        return self._run.run_id

    @property
    def recursion_depth(self) -> int:
        return self._run.depth

    # -- interaction ----------------------------------------------------
    def log(self, message: str, level: str = "info") -> None:
        self._run.emit_log(self.node.id, self.definition.name, str(message), level)

    def debug(self, message: str) -> None:
        self.log(message, "debug")

    def warning(self, message: str) -> None:
        self.log(message, "warning")

    def error(self, message: str) -> None:
        self.log(message, "error")

    def emit(self, kind: str, **payload: Any) -> None:
        self._run.emit(kind, node_id=self.node.id, **payload)

    def check_cancelled(self) -> None:
        if self._run.cancel_event.is_set():
            raise ExecutionCancelled("execution cancelled")

    def raise_if_limit(self) -> None:
        self._run.check_limits()

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.check_cancelled()
        try:
            await asyncio.wait_for(self._run.cancel_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
        raise ExecutionCancelled("execution cancelled")

    async def run_blocking(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run a blocking call on the run's worker pool, staying cancellable."""
        loop = asyncio.get_running_loop()
        future = asyncio.wrap_future(self._run.executor.submit(fn, *args, **kwargs))
        cancel_wait = asyncio.ensure_future(self._run.cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {future, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if future in done:
                return future.result()
            raise ExecutionCancelled("execution cancelled")
        finally:
            cancel_wait.cancel()
            if future.done() and not future.cancelled():
                future.exception()  # mark retrieved

    async def call_function(self, function_id: str, inputs: dict) -> dict:
        return await self._run.call_function(function_id, inputs, parent_ctx=self)

    def resolve_function(self, ref: str):
        """Look up a function by id or by name (used by loop nodes)."""
        library = self._run.executor.functions
        if not ref:
            return None
        return library.get(str(ref)) or library.by_name(str(ref))

    async def emit_event(self, name: str, payload: Any = None) -> None:
        self._run.event_bus.emit(name, payload)

    async def wait_for_event(self, name: str, timeout: float = 5.0) -> Any:
        return await self._run.event_bus.wait(name, timeout)

    def format_value(self, value: Any) -> str:
        from ..debugger.values import format_value

        return format_value(value)

    def now(self) -> float:
        return time.perf_counter()
