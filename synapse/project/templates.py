"""Project templates.

Each template builds a real, runnable project - no placeholders.  Templates
are functions rather than data files so they follow the node registry's current
type ids.
"""

from __future__ import annotations

from ..functions.library import FunctionDef, new_function_id
from ..graph.model import Graph
from ..nodes.base import PortSpec
from ..typesystem import DataType
from .model import Project

TEMPLATES = ("Blank", "Arithmetic", "Function", "Loop", "JSON", "Python Script")


def _function(name: str, graph: Graph, inputs, outputs, description: str) -> FunctionDef:
    return FunctionDef(
        id=new_function_id(),
        name=name,
        graph=graph,
        inputs=list(inputs),
        outputs=list(outputs),
        description=description,
    )


def _blank(registry) -> Project:
    return Project(name="Untitled", graphs={"g_main": Graph("g_main", "Main", registry=registry)})


def _arithmetic(registry) -> Project:
    project = _blank(registry)
    graph = project.main_graph
    a = graph.add_node("core.constant", {"value": "6"}, (40, 60))
    b = graph.add_node("core.constant", {"value": "7"}, (40, 200))
    mul = graph.add_node("math.multiply", {}, (300, 110))
    out = graph.add_node("core.graph_output", {"name": "product"}, (560, 120))
    graph.connect(a.id, "value", mul.id, "a")
    graph.connect(b.id, "value", mul.id, "b")
    graph.connect(mul.id, "result", out.id, "value")
    project.name = "Arithmetic"
    return project


def _function_project(registry) -> Project:
    project = _blank(registry)
    body = Graph("g_double", "Double", registry=registry)
    body.inputs = [PortSpec("x", DataType.INTEGER)]
    body.outputs = [PortSpec("result", DataType.INTEGER)]
    source = body.add_node("core.graph_input", {"name": "x", "variable_type": "integer"}, (20, 80))
    two = body.add_node("core.constant", {"value": "2"}, (20, 210))
    mul = body.add_node("math.multiply", {}, (260, 110))
    sink = body.add_node("core.graph_output", {"name": "result"}, (520, 120))
    body.connect(source.id, "value", mul.id, "a")
    body.connect(two.id, "value", mul.id, "b")
    body.connect(mul.id, "result", sink.id, "value")

    double = _function("Double", body, [PortSpec("x", DataType.INTEGER)],
                       [PortSpec("result", DataType.INTEGER)], "Doubles a number.")
    project.add_function(double, registry=registry)

    main = project.main_graph
    value = main.add_node("core.constant", {"value": "21"}, (40, 100))
    call = main.add_node(double.type_id, {}, (300, 80))
    out = main.add_node("core.graph_output", {"name": "doubled"}, (560, 100))
    main.connect(value.id, "value", call.id, "x")
    main.connect(call.id, "result", out.id, "value")
    project.name = "Function Demo"
    project.description = "A reusable function doubles 21."
    return project


def _loop_project(registry) -> Project:
    project = _blank(registry)
    body = Graph("g_sum", "Add To Total", registry=registry)
    body.inputs = [PortSpec("item", DataType.ANY), PortSpec("accumulator", DataType.ANY, default=0)]
    body.outputs = [PortSpec("result", DataType.ANY), PortSpec("accumulator", DataType.ANY)]
    item = body.add_node("core.graph_input", {"name": "item"}, (20, 60))
    acc = body.add_node("core.graph_input", {"name": "accumulator"}, (20, 200))
    add = body.add_node("math.add", {}, (280, 120))
    result = body.add_node("core.graph_output", {"name": "result"}, (540, 80))
    total = body.add_node("core.graph_output", {"name": "accumulator"}, (540, 220))
    body.connect(item.id, "value", add.id, "a")
    body.connect(acc.id, "value", add.id, "b")
    body.connect(add.id, "result", result.id, "value")
    body.connect(add.id, "result", total.id, "value")

    step = _function("Add To Total", body,
                     list(body.inputs), list(body.outputs),
                     "Adds one item to a running total.")
    project.add_function(step, registry=registry)

    main = project.main_graph
    items = main.add_node("core.constant", {"value": "[1, 2, 3, 4, 5]"}, (40, 80))
    zero = main.add_node("core.constant", {"value": "0"}, (40, 240))
    loop = main.add_node("logic.for_loop", {"body": step.id}, (300, 110))
    out = main.add_node("core.graph_output", {"name": "sum"}, (620, 60))
    count = main.add_node("core.graph_output", {"name": "iterations"}, (620, 220))
    main.connect(items.id, "value", loop.id, "items")
    main.connect(zero.id, "value", loop.id, "initial_accumulator")
    main.connect(loop.id, "accumulator", out.id, "value")
    main.connect(loop.id, "iterations", count.id, "value")
    project.name = "Loop Demo"
    project.description = "Sums an array by calling a function for every item."
    return project


def _json_project(registry) -> Project:
    project = _blank(registry)
    graph = project.main_graph
    payload = graph.add_node(
        "core.constant",
        {"value": '{"user": {"name": "Ada", "roles": ["admin", "engineer"]}}'},
        (40, 60),
    )
    query = graph.add_node("data.json_query", {"path": "user.roles.1"}, (420, 60))
    out = graph.add_node("core.graph_output", {"name": "role"}, (700, 80))
    graph.connect(payload.id, "value", query.id, "value")
    graph.connect(query.id, "value", out.id, "value")
    project.name = "JSON Demo"
    project.description = "Parses JSON and reads a nested field."
    return project


SCRIPT = """values = inputs.get('values', [])
result = {
    'total': sum(values),
    'mean': (sum(values) / len(values)) if values else 0,
    'squares': [v * v for v in values],
}
"""


def _script_project(registry) -> Project:
    project = _blank(registry)
    graph = project.main_graph
    data = graph.add_node("core.constant", {"value": '{"values": [4, 8, 15, 16, 23, 42]}'}, (40, 80))
    script = graph.add_node("script.python", {"code": SCRIPT}, (320, 60))
    out = graph.add_node("core.graph_output", {"name": "stats"}, (640, 90))
    graph.connect(data.id, "value", script.id, "inputs")
    graph.connect(script.id, "result", out.id, "value")
    project.name = "Script Demo"
    project.description = "Runs Python in the sandbox and returns a dictionary."
    return project


_BUILDERS = {
    "Blank": _blank,
    "Arithmetic": _arithmetic,
    "Function": _function_project,
    "Loop": _loop_project,
    "JSON": _json_project,
    "Python Script": _script_project,
}


def create_project(template: str, registry) -> Project:
    builder = _BUILDERS.get(template)
    if builder is None:
        raise KeyError(f"unknown template '{template}'")
    return builder(registry)
