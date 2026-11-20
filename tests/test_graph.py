import json

import pytest

from conftest import build_sum_graph
from synapse.graph.model import Graph, GraphError
from synapse.typesystem import DataType, PortSpec


def test_serialisation_roundtrip(registry):
    g = build_sum_graph(registry, 2, 3)
    g.add_frame("Group", (10, 10, 200, 120))
    data = g.to_dict()
    json.dumps(data)
    restored = Graph.from_dict(data, registry=registry)
    assert restored.to_dict() == data
    assert len(restored.nodes) == 4 and len(restored.edges) == 3


def test_unknown_node_type_is_rejected(registry):
    g = Graph("g", "G", registry=registry)
    with pytest.raises(GraphError):
        g.add_node("does.not.exist")


def test_cycle_is_rejected(registry):
    g = Graph("g", "G", registry=registry)
    a = g.add_node("math.add")
    b = g.add_node("math.add")
    g.connect(a.id, "result", b.id, "a")
    with pytest.raises(GraphError, match="cycle"):
        g.connect(b.id, "result", a.id, "a")


def test_incompatible_connection_is_rejected(registry):
    g = Graph("g", "G", registry=registry)
    text = g.add_node("data.string", {"text": "hello"})
    pick = g.add_node("data.dict_get", {"key": "a"})
    with pytest.raises(GraphError):
        g.connect(text.id, "value", pick.id, "dictionary")


def test_duplicate_edge_is_rejected(registry):
    g = build_sum_graph(registry, 1, 2)
    edge = g.edges[0]
    with pytest.raises(GraphError):
        g.connect(edge.source, edge.source_port, edge.target, edge.target_port)


def test_clone_assigns_new_ids(registry):
    g = build_sum_graph(registry, 1, 2)
    clone = g.clone()
    assert not set(clone.nodes) & set(g.nodes)
    assert len(clone.edges) == len(g.edges)
    assert clone.validate() == []


def test_remove_nodes_removes_edges(registry):
    g = build_sum_graph(registry, 1, 2)
    first = next(n.id for n in g.nodes.values() if n.type == "math.add")
    g.remove_nodes([first])
    assert first not in g.nodes
    assert all(e.source != first and e.target != first for e in g.edges)
    # the output node is now unconnected, which validation reports as an error
    assert any("not connected" in msg for msg in g.validate())


def test_graph_ports(registry):
    g = Graph("g", "G", registry=registry)
    g.inputs.append(PortSpec("a", DataType.INTEGER))
    g.outputs.append(PortSpec("b"))
    source = g.add_node("core.graph_input", {"name": "a", "variable_type": "integer"})
    g.add_node("core.graph_output", {"name": "b"})
    assert [p.name for p in g.inputs] == ["a"]
    assert [p.name for p in g.outputs] == ["b"]
    assert [p.name for p in g.output_ports(source)] == ["value"]
