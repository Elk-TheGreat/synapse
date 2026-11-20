"""Turn a selection of nodes into a reusable function.

The operation is purely structural: the selected nodes are copied into a new
graph, every external incoming edge becomes a ``core.graph_input`` node and
every external outgoing edge becomes a ``core.graph_output`` node.  The caller
replaces the selection with a single call to the new function and rewires the
external edges.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..graph.model import Edge, Graph, NodeInstance
from ..typesystem import DataType, PortSpec
from .library import FunctionDef, new_function_id

_EXTERNAL_INPUT_NODE = "core.graph_input"
_EXTERNAL_OUTPUT_NODE = "core.graph_output"


@dataclass
class Extraction:
    function: FunctionDef
    input_links: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    output_links: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    input_sources: dict[str, tuple[str, str]] = field(default_factory=dict)
    call_position: tuple[float, float] = (0.0, 0.0)
    call_label: str = ""


def _slug(value: str, fallback: str = "value") -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip()).strip("_").lower()
    if not text:
        text = fallback
    if text[0].isdigit():
        text = f"v_{text}"
    return text


def _unique(name: str, used: set[str]) -> str:
    candidate = name
    index = 2
    while candidate in used:
        candidate = f"{name}_{index}"
        index += 1
    used.add(candidate)
    return candidate


class ExtractionError(ValueError):
    """The selection cannot be turned into a function."""


def extract_function(
    graph: Graph,
    node_ids: list[str],
    *,
    name: str = "Function",
    description: str = "",
    registry=None,
) -> Extraction:
    selected = [node_ids] if isinstance(node_ids, str) else list(node_ids)
    if not selected:
        raise ExtractionError("select at least one node to convert into a function")
    missing = [n for n in selected if n not in graph.nodes]
    if missing:
        raise ExtractionError(f"unknown nodes in selection: {', '.join(sorted(missing))}")
    inside = set(selected)

    incoming = [e for e in graph.edges if e.target in inside and e.source not in inside]
    outgoing = [e for e in graph.edges if e.source in inside and e.target not in inside]

    function_graph = Graph(
        name=name,
        description=description or f"Extracted from {graph.name}",
        registry=registry or graph.registry,
    )
    id_map: dict[str, str] = {}
    min_x = min(graph.nodes[n].x for n in inside)
    min_y = min(graph.nodes[n].y for n in inside)
    for node_id in selected:
        node = graph.nodes[node_id]
        copy = NodeInstance(
            id=node.id,
            type=node.type,
            params=dict(node.params),
            x=node.x - min_x + 60.0,
            y=node.y - min_y + 120.0,
            width=node.width,
            height=node.height,
            label=node.label,
            disabled=node.disabled,
            version=node.version,
            notes=node.notes,
        )
        function_graph.nodes[copy.id] = copy
        id_map[node.id] = copy.id

    internal_edges = [
        e for e in graph.edges if e.source in inside and e.target in inside
    ]
    for edge in internal_edges:
        function_graph.connect(
            id_map[edge.source], edge.source_port, id_map[edge.target], edge.target_port
        )

    source_specs: dict[tuple[str, str], PortSpec] = {}
    for edge in incoming:
        source_specs[(edge.source, edge.source_port)] = _port(
            graph.output_ports(edge.source), edge.source_port
        )
    target_specs: dict[tuple[str, str], PortSpec] = {}
    for edge in outgoing:
        target_specs[(edge.source, edge.source_port)] = _port(
            graph.output_ports(edge.source), edge.source_port
        )

    # Group external inputs by their upstream port: one function parameter can
    # feed several internal nodes.
    used: set[str] = set()
    input_names: dict[tuple[str, str], str] = {}
    input_nodes: dict[tuple[str, str], NodeInstance] = {}
    input_links: dict[str, list[tuple[str, str]]] = {}
    input_sources: dict[str, tuple[str, str]] = {}
    x = 60.0
    for edge in sorted(incoming, key=lambda e: (graph.nodes[e.target].y, e.target)):
        key = (edge.source, edge.source_port)
        if key not in input_names:
            label = graph.nodes[edge.target].label or graph.nodes[edge.target].type.split(".")[-1]
            base = _slug(f"{label}_{edge.target_port}")
            port_name = _unique(base, used)
            spec = source_specs[key]
            input_names[key] = port_name
            port = PortSpec(port_name, spec.type, description=f"from {graph.nodes[edge.source].label or edge.source}")
            function_graph.inputs.append(port)
            node = function_graph.add_node(
                _EXTERNAL_INPUT_NODE, {"name": port_name, "variable_type": spec.type.value}, (x, 20.0)
            )
            node.label = port_name
            input_nodes[key] = node
            input_links[port_name] = []
            input_sources[port_name] = key
            x += 220.0
        port_name = input_names[key]
        function_graph.connect(input_nodes[key].id, "value", id_map[edge.target], edge.target_port)
        input_links[port_name].append((edge.target, edge.target_port))

    used_outputs: set[str] = set()
    output_names: dict[tuple[str, str], str] = {}
    output_links: dict[str, list[tuple[str, str]]] = {}
    out_x = 60.0
    for edge in sorted(outgoing, key=lambda e: (graph.nodes[e.source].x, e.source)):
        key = (edge.source, edge.source_port)
        if key not in output_names:
            spec = target_specs[key]
            base = _slug(edge.source_port or "result")
            port_name = _unique(base, used_outputs)
            output_names[key] = port_name
            function_graph.outputs.append(PortSpec(port_name, spec.type))
            node = function_graph.add_node(
                _EXTERNAL_OUTPUT_NODE,
                {"name": port_name},
                (out_x, 320.0),
            )
            node.label = port_name
            function_graph.connect(id_map[edge.source], edge.source_port, node.id, "value")
            output_links[port_name] = []
            out_x += 220.0
        output_links[output_names[key]].append((edge.target, edge.target_port))

    function = FunctionDef(
        id=new_function_id(),
        name=name or "Function",
        graph=function_graph,
        inputs=list(function_graph.inputs),
        outputs=list(function_graph.outputs),
        description=description,
    )
    call_position = (min_x, min_y)
    return Extraction(
        function=function,
        input_links=input_links,
        output_links=output_links,
        input_sources=input_sources,
        call_position=call_position,
        call_label=name,
    )


def _port(ports: list[PortSpec], name: str) -> PortSpec:
    for port in ports:
        if port.name == name:
            return port
    return PortSpec(name, DataType.ANY)
