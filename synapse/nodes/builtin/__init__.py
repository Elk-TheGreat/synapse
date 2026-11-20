"""Builtin node library.

Importing this package registers every decorated node with the registry passed
to :func:`register_builtin_nodes`.  Modules are imported once per process, so
several registries (tests, plugins) get independent copies of the definitions.
"""

from __future__ import annotations

from importlib import import_module
from typing import Iterable

from ..registry import NodeRegistry

MODULES: tuple[str, ...] = (
    "core",
    "logic",
    "math",
    "data",
    "files",
    "network",
    "ai",
    "graphics",
    "system",
    "scripting",
)


def _definitions(module) -> Iterable:
    seen = set()
    for value in vars(module).values():
        definition = getattr(value, "definition", None)
        if definition is None or definition.type_id in seen:
            continue
        seen.add(definition.type_id)
        yield definition


def register_builtin_nodes(registry: NodeRegistry) -> NodeRegistry:
    """Populate ``registry`` with the builtin nodes and the dynamic function adapter."""
    for name in MODULES:
        module = import_module(f".{name}", __name__)
        registry.register_many(list(_definitions(module)))

    from .functions import execute_function_node
    from ..base import make_definition

    if registry.get("fn.call") is None:
        # Placeholder type used by the inspector preview; real functions are
        # registered dynamically as fn.<id> by the project/function library.
        registry.register(
            make_definition(
                "fn.call",
                "Function Call",
                "Functions",
                description="Calls a user-defined function (choose one in the inspector).",
                inputs=[],
                outputs=[("result", "any")],
                execute=execute_function_node,
                source="builtin",
                dynamic=True,
            ),
            replace=True,
        )
    return registry


__all__ = ["register_builtin_nodes", "MODULES"]
