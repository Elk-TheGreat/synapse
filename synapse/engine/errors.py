"""Execution errors."""

from __future__ import annotations


class ExecutionError(Exception):
    """Base class for execution failures."""


class ExecutionCancelled(ExecutionError):
    """The run was cancelled by the user or the environment."""


class ExecutionLimitExceeded(ExecutionError):
    """A run limit (steps, time, recursion) was hit."""


class NodeExecutionError(ExecutionError):
    """A node raised an error while executing."""

    def __init__(
        self,
        message: str,
        *,
        node_id: str = "",
        node_name: str = "",
        node_type: str = "",
        details: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.node_id = node_id
        self.node_name = node_name
        self.node_type = node_type
        self.details = details

    def __str__(self) -> str:
        label = self.node_name or self.node_type or self.node_id
        return f"{label}: {self.message}" if label else self.message


class SecurityError(ExecutionError):
    """A node tried to do something the current policy forbids."""


class ControlFlowSignal(ExecutionError):
    """A break/continue raised inside a node, travelling to the nearest loop.

    The executor stops the current graph and hands the signal to the caller
    (``Executor.run_function_call``) instead of reporting it as an error.
    """

    def __init__(self, kind: str, value: object = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.value = value
