"""Node registry: the catalogue of everything placeable in a graph."""

from __future__ import annotations

import threading
from typing import Iterable

from .base import NodeDefinition


class NodeRegistry:
    """A thread-safe, ordered catalogue of node definitions."""

    def __init__(self) -> None:
        self._defs: dict[str, NodeDefinition] = {}
        self._lock = threading.RLock()
        self._listeners: list = []

    # -- registration ---------------------------------------------------
    def register(self, definition: NodeDefinition, *, replace: bool = False) -> NodeDefinition:
        if not isinstance(definition, NodeDefinition):
            raise TypeError("register() expects a NodeDefinition")
        if not definition.type_id:
            raise ValueError("node definition needs a type_id")
        with self._lock:
            if definition.type_id in self._defs and not replace:
                raise ValueError(f"node type '{definition.type_id}' is already registered")
            self._defs[definition.type_id] = definition
        self._notify()
        return definition

    def register_many(self, definitions: Iterable[NodeDefinition]) -> None:
        for definition in definitions:
            self.register(definition, replace=True)

    def unregister(self, type_id: str) -> NodeDefinition | None:
        with self._lock:
            definition = self._defs.pop(type_id, None)
        if definition is not None:
            self._notify()
        return definition

    def unregister_source(self, source: str) -> list[str]:
        with self._lock:
            removed = [tid for tid, d in self._defs.items() if d.source == source]
            for tid in removed:
                del self._defs[tid]
        if removed:
            self._notify()
        return removed

    # -- lookup ---------------------------------------------------------
    def get(self, type_id: str) -> NodeDefinition | None:
        return self._defs.get(type_id)

    def require(self, type_id: str) -> NodeDefinition:
        definition = self.get(type_id)
        if definition is None:
            raise KeyError(f"unknown node type '{type_id}'")
        return definition

    def all(self) -> list[NodeDefinition]:
        return sorted(self._defs.values(), key=lambda d: (d.category, d.name.lower()))

    def by_category(self) -> dict[str, list[NodeDefinition]]:
        result: dict[str, list[NodeDefinition]] = {}
        for definition in self.all():
            result.setdefault(definition.category, []).append(definition)
        return result

    def search(self, query: str) -> list[NodeDefinition]:
        query = query.strip().lower()
        if not query:
            return self.all()
        tokens = [t for t in query.split() if t]
        scored: list[tuple[int, NodeDefinition]] = []
        for definition in self._defs.values():
            haystack = " ".join(
                [
                    definition.name,
                    definition.type_id,
                    definition.category,
                    definition.description,
                    " ".join(definition.keywords),
                ]
            ).lower()
            score = 0
            for token in tokens:
                if token in definition.name.lower():
                    score += 5
                elif token in definition.category.lower():
                    score += 3
                elif token in haystack:
                    score += 1
                else:
                    score = -1
                    break
            if score > 0:
                scored.append((score, definition))
        scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
        return [definition for _, definition in scored]

    # -- observer -------------------------------------------------------
    def add_listener(self, callback) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # listeners must never break registration
                pass


_default: NodeRegistry | None = None
_default_lock = threading.Lock()


def default_registry() -> NodeRegistry:
    """The process-wide registry, populated with builtin nodes on first use."""
    global _default
    with _default_lock:
        if _default is None:
            from .builtin import register_builtin_nodes

            registry = NodeRegistry()
            register_builtin_nodes(registry)
            _default = registry
    return _default


def create_registry(*, include_builtin: bool = True) -> NodeRegistry:
    """A fresh registry (tests, plugins, isolated projects)."""
    registry = NodeRegistry()
    if include_builtin:
        from .builtin import register_builtin_nodes

        register_builtin_nodes(registry)
    return registry


def register_definition(definition: NodeDefinition) -> NodeDefinition:
    """Convenience used by builtin modules at import time."""
    return definition
