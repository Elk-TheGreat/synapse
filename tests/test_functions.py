import asyncio

from synapse.engine.executor import ExecutionOptions, Executor
from synapse.functions.extract import ExtractionError, extract_function
from synapse.functions.library import FunctionLibrary
from synapse.graph.model import Graph
from synapse.nodes.registry import create_registry


def _run(executor, graph, library, inputs=None):
    return asyncio.run(executor.run(graph, inputs=inputs, options=ExecutionOptions()))


def test_extract_function_and_reuse(registry):
    g = Graph("g", "Main", registry=registry)
    a = g.add_node("core.constant", {"value_type": "json", "value": "10"})
    b = g.add_node("core.constant", {"value_type": "json", "value": "4"})
    add = g.add_node("math.add")
    out = g.add_node("core.graph_output", {"name": "sum"})
    g.connect(a.id, "value", add.id, "a")
    g.connect(b.id, "value", add.id, "b")
    g.connect(add.id, "result", out.id, "value")

    extraction = extract_function(g, [add.id], name="Sum", description="Adds two numbers", registry=registry)
    function = extraction.function
    assert [p.name for p in function.inputs] and [p.name for p in function.outputs]
    # add node, one input node per upstream port (a, b), one output node
    assert len(function.graph.nodes) == 4
    assert [p.name for p in function.inputs] == ["add_a", "add_b"]
    assert function.description == "Adds two numbers"

    library = FunctionLibrary(registry)
    library.add(function, register=True)
    g.remove_nodes([add.id])
    call = g.add_node(function.type_id)
    for port_name, (source_id, source_port) in extraction.input_sources.items():
        g.connect(source_id, source_port, call.id, port_name)
    for port_name, links in extraction.output_links.items():
        for target_id, target_port in links:
            g.connect(call.id, port_name, target_id, target_port)

    executor = Executor(registry, functions=library)
    try:
        result = _run(executor, g, library)
    finally:
        executor.shutdown()
    assert result.ok, result.summary()
    assert result.outputs == {"sum": 14}


def test_extraction_requires_selection(registry):
    g = Graph("g", "Main", registry=registry)
    try:
        extract_function(g, [])
    except ExtractionError as exc:
        assert "select" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ExtractionError")


def test_function_roundtrip_and_params(registry):
    from synapse.project.templates import create_project

    project = create_project("Function", registry)
    function = project.functions[0]
    data = function.to_dict()
    from synapse.functions.library import FunctionDef

    restored = FunctionDef.from_dict(data, registry=registry)
    assert restored.name == function.name
    assert [p.name for p in restored.inputs] == [p.name for p in function.inputs]
    assert len(restored.graph.nodes) == len(function.graph.nodes)


def test_missing_function_reported(registry):
    from synapse.project.templates import create_project

    project = create_project("Function", registry)
    executor = Executor(registry, functions=FunctionLibrary(registry))
    try:
        result = _run(executor, project.main_graph, FunctionLibrary(registry))
    finally:
        executor.shutdown()
    assert result.status == "error"
    assert "not available" in str(result.errors[0])


def test_nested_function_calls(registry):
    from synapse.project.templates import create_project

    project = create_project("Function", registry)
    inner = project.functions[0]
    outer_graph = Graph("g_outer", "Outer", registry=registry)
    param = outer_graph.add_node("core.graph_input", {"name": "n"})
    call_inner = outer_graph.add_node(inner.type_id)
    ret = outer_graph.add_node("core.graph_output", {"name": "value"})
    outer_graph.inputs.append(param_spec("n"))
    outer_graph.outputs.append(param_spec("value"))
    outer_graph.connect(param.id, "value", call_inner.id, "x")
    outer_graph.connect(call_inner.id, "result", ret.id, "value")
    from synapse.functions.library import FunctionDef, new_function_id

    outer = FunctionDef(id=new_function_id(), name="Outer", graph=outer_graph,
                        inputs=list(outer_graph.inputs), outputs=list(outer_graph.outputs))
    library = FunctionLibrary(registry)
    library.add(inner, register=True)
    library.add(outer, register=True)

    main = Graph("g_main", "Main", registry=registry)
    value = main.add_node("core.constant", {"value_type": "json", "value": "5"})
    call = main.add_node(outer.type_id)
    out = main.add_node("core.graph_output", {"name": "result"})
    main.connect(value.id, "value", call.id, "n")
    main.connect(call.id, "value", out.id, "value")
    executor = Executor(registry, functions=library)
    try:
        result = _run(executor, main, library)
    finally:
        executor.shutdown()
    assert result.ok, result.summary()
    assert result.outputs == {"result": 10}


def param_spec(name):
    from synapse.typesystem import ANY, PortSpec

    return PortSpec(name, ANY)
