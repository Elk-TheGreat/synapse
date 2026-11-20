import asyncio

from conftest import build_sum_graph
from synapse.debugger.session import DebugSession
from synapse.engine.executor import ExecutionOptions, Executor


def test_breakpoint_pauses_and_resumes(registry):
    g = build_sum_graph(registry, 2, 5)
    add = next(n for n in g.nodes.values() if n.type == "math.add")
    session = DebugSession()
    session.add_breakpoint(g.id, add.id)
    executor = Executor(registry)

    async def scenario():
        task = asyncio.create_task(executor.run(g, debugger=session))
        for _ in range(200):
            if session.paused:
                break
            await asyncio.sleep(0.005)
        assert session.paused and session.paused_node == add.id
        assert sorted(session.paused_inputs) == ["a", "b"]
        session.resume()
        return await asyncio.wait_for(task, 5)

    try:
        result = asyncio.run(scenario())
    finally:
        executor.shutdown()
    assert result.ok and result.outputs == {"sum": 7}
    assert session.visited and session.finished
    assert any(entry.status == "ok" and entry.outputs for entry in session.history)


def test_step_over_visits_every_node(registry):
    g = build_sum_graph(registry, 1, 1)
    session = DebugSession()
    session.step_over()
    executor = Executor(registry)

    async def scenario():
        task = asyncio.create_task(executor.run(g, debugger=session))
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.05)
            if done:
                return await task
            session.step_over()

    try:
        result = asyncio.run(scenario())
    finally:
        executor.shutdown()
    assert result.ok
    assert len(session.history) == len(g.nodes)


def test_stop_cancels_run(registry):
    g = build_sum_graph(registry, 3, 3)
    session = DebugSession()
    session.add_breakpoint(g.id, next(iter(g.nodes)))
    executor = Executor(registry)

    async def scenario():
        task = asyncio.create_task(executor.run(g, debugger=session))
        for _ in range(200):
            if session.paused:
                break
            await asyncio.sleep(0.005)
        session.stop()
        return await asyncio.wait_for(task, 5)

    try:
        result = asyncio.run(scenario())
    finally:
        executor.shutdown()
    assert result.status == "cancelled" and result.outputs == {}


def test_history_records_durations(registry):
    g = build_sum_graph(registry, 8, 9)
    session = DebugSession()
    executor = Executor(registry)
    try:
        result = asyncio.run(executor.run(g, debugger=session, options=ExecutionOptions()))
    finally:
        executor.shutdown()
    assert result.ok
    assert all(entry.duration >= 0 for entry in session.history)
    assert {entry.node_id for entry in session.history} == set(g.nodes)
    assert not session.paused
