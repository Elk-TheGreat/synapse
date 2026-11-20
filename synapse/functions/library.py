"""Function library: reusable sub-graphs stored at project level."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..graph.model import Graph
from ..nodes.base import NodeDefinition, ParamSpec, PortSpec
from ..typesystem import DataType


def new_function_id() -> str:
    return "fn_" + uuid.uuid4().hex[:10]


@dataclass
class FunctionDef:
    """A named sub-graph with typed parameters and return values."""

    id: str
    name: str
    graph: Graph
    inputs: list[PortSpec] = field(default_factory=list)
    outputs: list[PortSpec] = field(default_factory=list)
    description: str = ""
    version: int = 1
    tags: list[str] = field(default_factory=list)

    @property
    def type_id(self) -> str:
        return f"fn.{self.id}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": list(self.tags),
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "graph": self.graph.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict, *, registry=None) -> "FunctionDef":
        graph_data = data.get("graph") or {}
        graph = Graph.from_dict(graph_data, registry=registry)
        graph.name = str(data.get("name", graph.name))
        return cls(
            id=str(data.get("id") or new_function_id()),
            name=str(data.get("name", "Function")),
            graph=graph,
            inputs=[PortSpec.from_dict(p) for p in data.get("inputs") or []],
            outputs=[PortSpec.from_dict(p) for p in data.get("outputs") or []],
            description=str(data.get("description", "")),
            version=int(data.get("version", 1)),
            tags=[str(t) for t in data.get("tags") or []],
        )

    def preview_signature(self) -> str:
        return f"{self.name}(" + ", ".join(p.name for p in self.inputs) + ")"

    def to_definition(self) -> NodeDefinition:
        """Node type used to call this function from another graph."""
        from ..nodes.builtin.functions import execute_function_node

        return NodeDefinition(
            type_id=self.type_id,
            name=self.name,
            category="Functions",
            description=self.description or f"Reusable function '{self.name}'",
            inputs=tuple(self.inputs),
            outputs=tuple(self.outputs),
            params={},
            version=self.version,
            pure=False,
            execute=execute_function_node,
            source="function",
            function_id=self.id,
            default_width=220.0,
            default_height=max(90.0, 40.0 + 18 * max(len(self.inputs), len(self.outputs))),
            keywords=(self.name.lower(), "function"),
        )


class FunctionLibrary:
    """Ordered set of functions plus registration into a node registry."""

    def __init__(self, registry=None) -> None:
        self._functions: dict[str, FunctionDef] = {}
        self._registry = registry

    def __len__(self) -> int:
        return len(self._functions)

    def __iter__(self) -> Iterator[FunctionDef]:
        return iter(self._functions.values())

    def __contains__(self, function_id: object) -> bool:
        return function_id in self._functions

    def get(self, function_id: str) -> FunctionDef | None:
        return self._functions.get(function_id)

    def by_name(self, name: str) -> FunctionDef | None:
        for function in self._functions.values():
            if function.name == name:
                return function
        return None

    def add(self, function: FunctionDef, *, register: bool = True) -> FunctionDef:
        if self.get(function.id) is not None:
            self.update(function)
            return function
        self._functions[function.id] = function
        if register and self._registry is not None:
            self._registry.register(function.to_definition(), replace=True)
        return function

    def update(self, function: FunctionDef) -> None:
        self._functions[function.id] = function
        if self._registry is not None:
            self._registry.register(function.to_definition(), replace=True)

    def remove(self, function_id: str) -> FunctionDef | None:
        function = self._functions.pop(function_id, None)
        if function is not None and self._registry is not None:
            self._registry.unregister(function.type_id)
        return function

    def all(self) -> list[FunctionDef]:
        return sorted(self._functions.values(), key=lambda f: f.name.lower())

    def to_list(self) -> list[dict]:
        return [f.to_dict() for f in self._functions.values()]

    def load_list(self, data: list[dict]) -> None:
        self._functions.clear()
        for raw in data:
            function = FunctionDef.from_dict(raw, registry=self._registry)
            self.add(function)

    def make(
        self,
        name: str,
        graph: Graph | None = None,
        *,
        inputs: list[PortSpec] | None = None,
        outputs: list[PortSpec] | None = None,
        description: str = "",
    ) -> FunctionDef:
        function = FunctionDef(
            id=new_function_id(),
            name=name,
            graph=graph or Graph(name=name, registry=self._registry),
            inputs=list(inputs or []),
            outputs=list(outputs or [PortSpec("result", DataType.ANY)]),
            description=description,
        )
        return self.add(function)


def function_node_params(function: FunctionDef) -> list[ParamSpec]:
    """Placeholder for future per-function configuration."""
    return []
