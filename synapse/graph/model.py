"""Typed graph model: nodes, ports, edges, frames and validation.

The graph is the program.  This module is purely a data model: it imports no
Qt code and no node implementations, only the node registry interface, which
is resolved lazily so the engine, compiler and tests can use graphs alone.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable

from ..typesystem import DataType, PortSpec, compatibility_error, is_compatible

if TYPE_CHECKING:  # pragma: no cover
    from ..nodes.registry import NodeDefinition, NodeRegistry


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:12]
    return f"{prefix}{raw}" if prefix else raw


class GraphError(ValueError):
    """Base class for graph errors."""


class ConnectionError_(GraphError):
    """A connection was rejected."""


class CycleError(GraphError):
    """The graph contains a cycle that cannot be executed."""


@dataclass
class NodeInstance:
    """A placed node inside a graph."""

    id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    width: float = 200.0
    height: float = 120.0
    label: str | None = None
    disabled: bool = False
    version: int = 1
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "params": dict(self.params),
            "position": [round(self.x, 2), round(self.y, 2)],
            "size": [round(self.width, 2), round(self.height, 2)],
            "label": self.label,
            "disabled": self.disabled,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NodeInstance":
        pos = data.get("position") or [0, 0]
        size = data.get("size") or [200, 120]
        node_id = data.get("id") or new_id("n_")
        if not isinstance(node_id, str) or not node_id:
            raise GraphError("node id must be a non-empty string")
        return cls(
            id=node_id,
            type=str(data.get("type", "")),
            params=dict(data.get("params") or {}),
            x=float(pos[0]),
            y=float(pos[1]),
            width=max(120.0, float(size[0])),
            height=max(60.0, float(size[1])),
            label=data.get("label"),
            disabled=bool(data.get("disabled", False)),
            version=int(data.get("version", 1)),
            notes=str(data.get("notes", "")),
        )


@dataclass
class Edge:
    """A directed, typed connection between two ports."""

    id: str
    source: str
    source_port: str
    target: str
    target_port: str
    source_type: str = DataType.ANY.value
    target_type: str = DataType.ANY.value

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "source_port": self.source_port,
            "target": self.target,
            "target_port": self.target_port,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Edge":
        try:
            return cls(
                id=data.get("id") or new_id("e_"),
                source=data["source"],
                source_port=data["source_port"],
                target=data["target"],
                target_port=data["target_port"],
            )
        except KeyError as exc:
            raise GraphError(f"edge is missing field {exc}") from exc


@dataclass
class Frame:
    """A visual group or a free annotation holding a set of nodes."""

    id: str
    title: str = "Group"
    x: float = 0.0
    y: float = 0.0
    width: float = 320.0
    height: float = 240.0
    color: str = "#38bdf8"
    node_ids: list[str] = field(default_factory=list)
    kind: str = "frame"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "position": [self.x, self.y],
            "size": [self.width, self.height],
            "color": self.color,
            "node_ids": list(self.node_ids),
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Frame":
        pos = data.get("position") or [0, 0]
        size = data.get("size") or [320, 240]
        return cls(
            id=data.get("id") or new_id("f_"),
            title=str(data.get("title", "Group")),
            x=float(pos[0]),
            y=float(pos[1]),
            width=float(size[0]),
            height=float(size[1]),
            color=str(data.get("color", "#38bdf8")),
            node_ids=[str(n) for n in data.get("node_ids") or []],
            kind=str(data.get("kind", "frame")),
        )


class Graph:
    """A program graph."""

    def __init__(
        self,
        graph_id: str | None = None,
        name: str = "Main",
        *,
        description: str = "",
        registry: "NodeRegistry | None" = None,
    ) -> None:
        self.id = graph_id or new_id("g_")
        self.name = name
        self.description = description
        self.nodes: dict[str, NodeInstance] = {}
        self.edges: list[Edge] = []
        self.frames: list[Frame] = []
        self.variables: dict[str, dict[str, Any]] = {}
        self.inputs: list[PortSpec] = []
        self.outputs: list[PortSpec] = []
        self.metadata: dict[str, Any] = {}
        self._registry = registry

    # -- registry -------------------------------------------------------
    @property
    def registry(self) -> "NodeRegistry":
        if self._registry is None:
            from ..nodes.registry import default_registry

            self._registry = default_registry()
        return self._registry

    def set_registry(self, registry: "NodeRegistry") -> None:
        self._registry = registry

    # -- nodes ----------------------------------------------------------
    def add_node(
        self,
        type_id: str,
        params: dict[str, Any] | None = None,
        position: tuple[float, float] = (0.0, 0.0),
        *,
        node_id: str | None = None,
        label: str | None = None,
    ) -> NodeInstance:
        definition = self.registry.get(type_id)
        if definition is None:
            raise GraphError(f"unknown node type '{type_id}'")
        node = NodeInstance(
            id=node_id or new_id("n_"),
            type=type_id,
            params=definition.default_params(),
            x=float(position[0]),
            y=float(position[1]),
            width=definition.default_width,
            height=definition.default_height,
            label=label,
            version=definition.version,
        )
        if params:
            node.params.update(params)
        self.nodes[node.id] = node
        return node

    def remove_nodes(self, node_ids: Iterable[str]) -> list[NodeInstance]:
        removed = []
        ids = set(node_ids)
        for node_id in ids:
            node = self.nodes.pop(node_id, None)
            if node is not None:
                removed.append(node)
        self.edges = [
            e for e in self.edges if e.source not in ids and e.target not in ids
        ]
        for frame in self.frames:
            frame.node_ids = [n for n in frame.node_ids if n not in ids]
        return removed

    def node(self, node_id: str) -> NodeInstance:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise GraphError(f"unknown node '{node_id}'") from exc

    def definition(self, node_or_id: NodeInstance | str) -> "NodeDefinition":
        node = node_or_id if isinstance(node_or_id, NodeInstance) else self.node(node_or_id)
        definition = self.registry.get(node.type)
        if definition is None:
            raise GraphError(f"unknown node type '{node.type}'")
        return definition

    def input_ports(self, node_or_id: NodeInstance | str) -> list[PortSpec]:
        return list(self.definition(node_or_id).resolve_inputs(self, node_or_id))

    def output_ports(self, node_or_id: NodeInstance | str) -> list[PortSpec]:
        return list(self.definition(node_or_id).resolve_outputs(self, node_or_id))

    # -- edges ----------------------------------------------------------
    def incoming(self, node_id: str, port: str | None = None) -> list[Edge]:
        return [
            e for e in self.edges
            if e.target == node_id and (port is None or e.target_port == port)
        ]

    def outgoing(self, node_id: str, port: str | None = None) -> list[Edge]:
        return [
            e for e in self.edges
            if e.source == node_id and (port is None or e.source_port == port)
        ]

    def edge_into(self, node_id: str, port: str) -> Edge | None:
        found = self.incoming(node_id, port)
        return found[0] if found else None

    def validate_connection(
        self,
        source: str,
        source_port: str,
        target: str,
        target_port: str,
    ) -> str | None:
        """Return an error message, or None when the connection is valid."""
        if source not in self.nodes:
            return f"unknown source node '{source}'"
        if target not in self.nodes:
            return f"unknown target node '{target}'"
        if source == target:
            return "a node cannot be connected to itself"
        try:
            out_ports = {p.name: p for p in self.output_ports(source)}
            in_ports = {p.name: p for p in self.input_ports(target)}
        except GraphError as exc:
            return str(exc)
        if source_port not in out_ports:
            return f"node '{source}' has no output port '{source_port}'"
        if target_port not in in_ports:
            return f"node '{target}' has no input port '{target_port}'"
        src_type, dst_type = out_ports[source_port], in_ports[target_port]
        if not is_compatible(src_type.spec, dst_type.spec):
            return compatibility_error(src_type.spec, dst_type.spec)
        existing = self.edge_into(target, target_port)
        if existing is not None:
            return (
                f"input '{target_port}' of '{target}' is already connected; "
                "disconnect it first"
            )
        if self._creates_cycle(source, target):
            return (
                "connection would create a cycle; use a function node or an "
                "explicit accumulator instead"
            )
        return None

    def connect(
        self,
        source: str,
        source_port: str,
        target: str,
        target_port: str,
        *,
        edge_id: str | None = None,
        replace: bool = False,
    ) -> Edge:
        error = self.validate_connection(source, source_port, target, target_port)
        if error and replace and error.startswith("input "):
            existing = self.edge_into(target, target_port)
            if existing is not None:
                self.edges.remove(existing)
            error = self.validate_connection(source, source_port, target, target_port)
        if error:
            raise ConnectionError_(error)
        out_ports = {p.name: p for p in self.output_ports(source)}
        in_ports = {p.name: p for p in self.input_ports(target)}
        edge = Edge(
            id=edge_id or new_id("e_"),
            source=source,
            source_port=source_port,
            target=target,
            target_port=target_port,
            source_type=out_ports[source_port].spec.type.value,
            target_type=in_ports[target_port].spec.type.value,
        )
        self.edges.append(edge)
        return edge

    def disconnect(self, edge_id: str) -> Edge | None:
        for edge in list(self.edges):
            if edge.id == edge_id:
                self.edges.remove(edge)
                return edge
        return None

    def _creates_cycle(self, source: str, target: str) -> bool:
        """Would adding source->target close a loop? (DFS from target)"""
        adj: dict[str, list[str]] = {}
        for edge in self.edges:
            adj.setdefault(edge.source, []).append(edge.target)
        stack = [target]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == source:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adj.get(current, ()))
        return False

    # -- frames ---------------------------------------------------------
    def add_frame(
        self,
        title: str,
        rect: tuple[float, float, float, float],
        node_ids: Iterable[str] = (),
        *,
        kind: str = "frame",
        color: str = "#38bdf8",
    ) -> Frame:
        frame = Frame(
            id=new_id("f_"),
            title=title,
            x=rect[0],
            y=rect[1],
            width=rect[2],
            height=rect[3],
            color=color,
            node_ids=list(node_ids),
            kind=kind,
        )
        self.frames.append(frame)
        return frame

    def remove_frame(self, frame_id: str) -> Frame | None:
        for frame in list(self.frames):
            if frame.id == frame_id:
                self.frames.remove(frame)
                return frame
        return None

    # -- execution helpers ---------------------------------------------
    def upstream_map(self) -> dict[str, dict[str, Edge]]:
        """node_id -> {input_port: edge}"""
        result: dict[str, dict[str, Edge]] = {node_id: {} for node_id in self.nodes}
        for edge in self.edges:
            result.setdefault(edge.target, {})[edge.target_port] = edge
        return result

    def downstream_map(self) -> dict[str, list[Edge]]:
        result: dict[str, list[Edge]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            result.setdefault(edge.source, []).append(edge)
        return result

    def topological_order(self) -> list[str]:
        deps = {node_id: set() for node_id in self.nodes}
        for edge in self.edges:
            if edge.target in deps and edge.source in deps:
                deps[edge.target].add(edge.source)
        order: list[str] = []
        ready = sorted(n for n, d in deps.items() if not d)
        remaining = {n: set(d) for n, d in deps.items() if d}
        while ready:
            current = ready.pop(0)
            order.append(current)
            for node_id, depset in list(remaining.items()):
                depset.discard(current)
                if not depset:
                    ready.append(node_id)
                    del remaining[node_id]
            ready.sort()
        if remaining:
            raise CycleError(
                "graph contains a cycle involving: "
                + ", ".join(sorted(remaining))
            )
        return order

    def validate(self) -> list[str]:
        """Structural validation used before saving or executing."""
        problems: list[str] = []
        for node in self.nodes.values():
            definition = self.registry.get(node.type)
            if definition is None:
                problems.append(f"node {node.id}: unknown type '{node.type}'")
                continue
            inputs = {p.name: p for p in definition.resolve_inputs(self, node)}
            outputs = {p.name: p for p in definition.resolve_outputs(self, node)}
            for port in node.params:
                if port not in definition.params and not definition.free_params:
                    problems.append(
                        f"node {node.id} ({definition.name}): unknown parameter '{port}'"
                    )
            for edge in self.incoming(node.id):
                if edge.target_port not in inputs:
                    problems.append(
                        f"edge {edge.id}: '{node.id}' has no input '{edge.target_port}'"
                    )
            for edge in self.outgoing(node.id):
                if edge.source_port not in outputs:
                    problems.append(
                        f"edge {edge.id}: '{node.id}' has no output '{edge.source_port}'"
                    )
            for spec in inputs.values():
                if not spec.optional and spec.default is None:
                    if self.edge_into(node.id, spec.name) is None:
                        if spec.name not in node.params:
                            problems.append(
                                f"node {node.id} ({definition.name}): required input "
                                f"'{spec.name}' is not connected"
                            )
        try:
            self.topological_order()
        except CycleError as exc:
            problems.append(str(exc))
        return problems

    def required_inputs(self, node: NodeInstance) -> list[PortSpec]:
        result = []
        for spec in self.input_ports(node):
            if spec.optional or spec.default is not None:
                continue
            result.append(spec)
        return result

    # -- serialization --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "frames": [f.to_dict() for f in self.frames],
            "variables": dict(self.variables),
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict, *, registry: "NodeRegistry | None" = None) -> "Graph":
        if not isinstance(data, dict):
            raise GraphError("graph must be a JSON object")
        graph = cls(
            graph_id=str(data.get("id") or new_id("g_")),
            name=str(data.get("name", "Graph")),
            description=str(data.get("description", "")),
            registry=registry,
        )
        for raw in data.get("nodes") or []:
            node = NodeInstance.from_dict(raw)
            if node.id in graph.nodes:
                raise GraphError(f"duplicate node id '{node.id}'")
            graph.nodes[node.id] = node
        for raw in data.get("edges") or []:
            edge = Edge.from_dict(raw)
            if edge.source not in graph.nodes or edge.target not in graph.nodes:
                raise GraphError(
                    f"edge {edge.id} references a missing node"
                )
            graph.edges.append(edge)
        for raw in data.get("frames") or []:
            graph.frames.append(Frame.from_dict(raw))
        graph.variables = dict(data.get("variables") or {})
        graph.inputs = [PortSpec.from_dict(p) for p in data.get("inputs") or []]
        graph.outputs = [PortSpec.from_dict(p) for p in data.get("outputs") or []]
        graph.metadata = dict(data.get("metadata") or {})
        return graph

    def clone(self, *, new_ids: bool = True) -> "Graph":
        copy = Graph.from_dict(self.to_dict(), registry=self._registry)
        if new_ids:
            mapping = {old: new_id("n_") for old in copy.nodes}
            for old, node in list(copy.nodes.items()):
                del copy.nodes[old]
                node.id = mapping[old]
                copy.nodes[node.id] = node
            for edge in copy.edges:
                edge.id = new_id("e_")
                edge.source = mapping.get(edge.source, edge.source)
                edge.target = mapping.get(edge.target, edge.target)
            for frame in copy.frames:
                frame.id = new_id("f_")
                frame.node_ids = [mapping.get(n, n) for n in frame.node_ids]
        copy.id = new_id("g_")
        return copy

    def bounds(self) -> tuple[float, float, float, float]:
        if not self.nodes:
            return (0.0, 0.0, 800.0, 600.0)
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        xe = [n.x + n.width for n in self.nodes.values()]
        ye = [n.y + n.height for n in self.nodes.values()]
        return (min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys))
