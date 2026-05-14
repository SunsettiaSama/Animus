from __future__ import annotations

from typing import Any, Mapping

from agent.flow.base.components import (
    ExecutionNodeSpec,
    MetadataLayer,
    RunnableExecutionNode,
    RunnableExecutionNodeWithHooks,
)


class _EchoExecutor:
    def run(self, spec: ExecutionNodeSpec, inputs: Mapping[str, Any]) -> Any:
        return {"task": spec.task_id, "in": dict(inputs)}


def test_runnable_execution_node_run() -> None:
    spec = ExecutionNodeSpec(metadata=MetadataLayer(task_id="t1"))
    node = RunnableExecutionNode(spec=spec, executor=_EchoExecutor())
    assert node.task_id == "t1"
    out = node.run({"q": 1})
    assert out == {"task": "t1", "in": {"q": 1}}


class _PassSecurity:
    def authorize(self, spec, caller):
        pass

    def audit_event(self, name, payload):
        pass


def test_runnable_with_hooks_skips_optional() -> None:
    spec = ExecutionNodeSpec(metadata=MetadataLayer(task_id="t2"))
    n = RunnableExecutionNodeWithHooks(spec=spec, executor=_EchoExecutor(), security=_PassSecurity())
    out = n.run(caller={}, upstream_outputs={"k": "v"})
    assert out["in"] == {"k": "v"}
