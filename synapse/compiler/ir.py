"""Shared intermediate representation for SYNAPSE programs.

Both code generation and external runners consume this representation, so the
graph the editor shows is the program that runs.  The IR is a resolved,
ordered view of a :class:`~synapse.graph.model.Graph`: every node carries its
definition, every input states where its value comes from, and the node order
is the topological order the engine executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..graph.model import Graph
from ..nodes.base import NodeDefinition
from ..typesystem import PortSpec


class CompileError(ValueError):
    """The graph cannot be turned into an executable plan."""


@dataclass(frozen=True)
class IRInput:
    """Where a node input gets its value: a wire, a parameter or a port default."""

    source_node: str | None = None
    source_port: str | None = None
    literal: Any = None
    from_param: bool = False

    @property
    def wired(self) -> bool:
        return self.source_node is not None


@dataclass
class IRNode:
    id: str
    type_id: str
    name: str
    category: str
    definition: NodeDefinition
    params: dict[str, Any]
    inputs: dict[str, IRInput]
    outputs: list[PortSpec]
    position: tuple[float, float] = (0.0, 0.0)
    disabled: bool = False
    pure: bool = True
    codegen: str = "unsupported"

    @property
    def label(self) -> str:
        return self.definition.name


@dataclass
class CompiledGraph:
    graph_id: str
    name: str
    inputs: list[PortSpec]
    outputs: list[PortSpec]
    nodes: list[IRNode]
    edges: list[dict[str, str]]
    variables: dict[str, Any] = field(default_factory=dict)
    functions: dict[str, "CompiledGraph"] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def node(self, node_id: str) -> IRNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    @property
    def order(self) -> list[str]:
        return [node.id for node in self.nodes]

    @property
    def external_inputs(self) -> list[PortSpec]:
        return [p for p in self.inputs if not p.optional]

    def unsupported_nodes(self) -> list[IRNode]:
        return [n for n in self.nodes if n.codegen == "unsupported"]

    def summary(self) -> str:
        return (
            f"{self.name}: {len(self.nodes)} nodes, {len(self.edges)} connections, "
            f"{len(self.inputs)} inputs, {len(self.outputs)} outputs"
        )


def _resolve_inputs(graph: Graph, node, definition: NodeDefinition) -> dict[str, IRInput]:
    incoming = {edge.target_port: edge for edge in graph.incoming(node.id)}
    resolved: dict[str, IRInput] = {}
    for port in definition.inputs:
        edge = incoming.get(port.name)
        if edge is not None:
            resolved[port.name] = IRInput(source_node=edge.source, source_port=edge.source_port)
            continue
        if port.name in node.params:
            resolved[port.name] = IRInput(literal=node.params[port.name], from_param=True)
            continue
        resolved[port.name] = IRInput(literal=port.default)
    return resolved


def build_ir(
    graph: Graph,
    *,
    functions=None,
    include_functions: bool = True,
    _stack: tuple[str, ...] = (),
) -> CompiledGraph:
    """Validate ``graph`` and return its ordered IR.

    ``functions`` is a :class:`~synapse.functions.library.FunctionLibrary`; when
    given, every function reachable from the graph is compiled too so that
    exporters can emit a self-contained program.
    """
    problems = graph.validate()
    if problems:
        raise CompileError("; ".join(problems))
    if graph.id in _stack:
        raise CompileError(f"function recursion through graph '{graph.name}' is not exportable")

    try:
        order = graph.topological_order()
    except Exception as exc:  # CycleError and friends
        raise CompileError(str(exc)) from exc

    nodes: list[IRNode] = []
    for node_id in order:
        node = graph.node(node_id)
        definition = graph.definition(node)
        nodes.append(
            IRNode(
                id=node.id,
                type_id=node.type,
                name=definition.name,
                category=definition.category,
                definition=definition,
                params=dict(node.params),
                inputs=_resolve_inputs(graph, node, definition),
                outputs=list(definition.outputs),
                position=(node.x, node.y),
                disabled=node.disabled,
                pure=definition.pure,
                codegen=definition.codegen,
            )
        )

    compiled = CompiledGraph(
        graph_id=graph.id,
        name=graph.name,
        inputs=list(graph.inputs),
        outputs=list(graph.outputs),
        nodes=nodes,
        edges=[
            {
                "id": edge.id,
                "source": edge.source,
                "source_port": edge.source_port,
                "target": edge.target,
                "target_port": edge.target_port,
            }
            for edge in graph.edges
        ],
        variables=dict(graph.variables),
    )
    for node in nodes:
        if node.disabled:
            compiled.warnings.append(f"node '{node.name}' is disabled and will not run")

    if include_functions and functions is not None:
        for node in nodes:
            function_id = node.definition.function_id
            if not function_id:
                continue
            function = functions.get(function_id)
            if function is None:
                raise CompileError(
                    f"node '{node.name}' calls missing function '{function_id}'"
                )
            if function.id in compiled.functions:
                continue
            compiled.functions[function.id] = build_ir(
                function.graph,
                functions=functions,
                include_functions=True,
                _stack=_stack + (graph.id,),
            )
    return compiled
