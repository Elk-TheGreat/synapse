"""Nodes that implement the function-call and loop surface of SYNAPSE.

A user function is exposed to graphs as a node whose ``function_id`` is set by
``FunctionDef.to_definition``; this module supplies that node's runtime body.

A loop calls its body function once per item; the body graph returns the
Break/Continue signal (see logic.py) and the loop decides whether to stop.
"""

from __future__ import annotations


async def execute_function_node(ctx, inputs, params):
    function_id = getattr(ctx.definition, "function_id", None)
    if not function_id and ctx.definition.type_id.startswith("fn."):
        function_id = ctx.definition.type_id[3:]
    if not function_id:
        raise RuntimeError(f"node type '{ctx.definition.type_id}' is not bound to a function")
    outputs = await ctx.call_function(str(function_id), dict(inputs))
    declared = [port.name for port in ctx.definition.outputs if not port.variadic]
    return {name: outputs.get(name) for name in declared}


# Loops live in logic.py ("For Loop", "While Loop"): they call a body function
# and read its Break/Continue "signal" output.  Only the call adapter is needed
# here because FunctionDef.to_definition() points at it.
