"""
十节点 DAG：仅用 ``ExecutionNodeSpec`` + ``RunnableExecutionNode`` + ``link.ready_ids``，
模拟调度器多波次执行；断言最终数值与波次顺序（节点行为 / 结果，不经过 HTTP）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent.flow.base.components import ExecutionNodeSpec, MetadataLayer, RunnableExecutionNode
from agent.flow.base.link import dep_map_from_nodes, ready_ids
from agent.flow.base.types import NodeStatus


class _UpstreamTableExecutor:
    """根据 ``task_id`` 查表，仅从 ``inputs['upstream']`` 读取依赖输出。"""

    def __init__(self, fn_by_task: dict[str, Callable[[dict[str, Any]], Any]]) -> None:
        self._fn = fn_by_task

    def run(self, spec: ExecutionNodeSpec, inputs: Mapping[str, Any]) -> Any:
        upstream: dict[str, Any] = dict(inputs.get("upstream") or {})
        return self._fn[spec.task_id](upstream)


def _ten_node_specs() -> tuple[ExecutionNodeSpec, ...]:
    """n0 为根；n1/n2 并行；n3 汇；n4 链；n5/n6 并行；n7 汇；n8-n9 链。"""
    return (
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n0", depends_on=())),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n1", depends_on=("n0",))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n2", depends_on=("n0",))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n3", depends_on=("n1", "n2"))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n4", depends_on=("n3",))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n5", depends_on=("n4",))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n6", depends_on=("n4",))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n7", depends_on=("n5", "n6"))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n8", depends_on=("n7",))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="n9", depends_on=("n8",))),
    )


def _ten_ops() -> dict[str, Callable[[dict[str, Any]], Any]]:
    return {
        "n0": lambda u: 1,
        "n1": lambda u: u["n0"] + 10,
        "n2": lambda u: u["n0"] * 2,
        "n3": lambda u: u["n1"] + u["n2"],
        "n4": lambda u: u["n3"] * 3,
        "n5": lambda u: u["n4"] + 1,
        "n6": lambda u: u["n4"] + 2,
        "n7": lambda u: u["n5"] + u["n6"],
        "n8": lambda u: u["n7"] - 1,
        "n9": lambda u: u["n8"] * 2,
    }


def _expected_n9() -> int:
    f = _ten_ops()
    n0 = f["n0"]({})
    n1 = f["n1"]({"n0": n0})
    n2 = f["n2"]({"n0": n0})
    n3 = f["n3"]({"n1": n1, "n2": n2})
    n4 = f["n4"]({"n3": n3})
    n5 = f["n5"]({"n4": n4})
    n6 = f["n6"]({"n4": n4})
    n7 = f["n7"]({"n5": n5, "n6": n6})
    n8 = f["n8"]({"n7": n7})
    return f["n9"]({"n8": n8})


def _run_dag(specs: tuple[ExecutionNodeSpec, ...]) -> tuple[Any, list[list[str]]]:
    ex = _UpstreamTableExecutor(_ten_ops())
    runnables = {s.task_id: RunnableExecutionNode(spec=s, executor=ex) for s in specs}
    deps = dep_map_from_nodes(specs)
    status: dict[str, NodeStatus] = {tid: NodeStatus.pending for tid in deps}
    outputs: dict[str, Any] = {}
    waves: list[list[str]] = []

    while any(st != NodeStatus.done for st in status.values()):
        tier_ready = ready_ids(specs, status)
        if not tier_ready:
            raise RuntimeError(f"deadlock or invalid graph: status={status!r} keys_out={sorted(outputs)}")
        waves.append(list(tier_ready))
        for tid in tier_ready:
            up = {d: outputs[d] for d in deps[tid]}
            out = runnables[tid].run({"upstream": up})
            outputs[tid] = out
            status[tid] = NodeStatus.done

    return outputs["n9"], waves


def test_ten_nodes_compute_expected_value() -> None:
    specs = _ten_node_specs()
    final, _waves = _run_dag(specs)
    assert final == _expected_n9()
    assert final == 160


def test_ten_nodes_wave_shape() -> None:
    """波次：n0 → n1,n2 → n3 → n4 → n5,n6 → n7 → n8 → n9（同层 id 排序）。"""
    specs = _ten_node_specs()
    _final, waves = _run_dag(specs)
    assert waves == [
        ["n0"],
        ["n1", "n2"],
        ["n3"],
        ["n4"],
        ["n5", "n6"],
        ["n7"],
        ["n8"],
        ["n9"],
    ]


def test_each_node_output_recorded() -> None:
    specs = _ten_node_specs()
    ex = _UpstreamTableExecutor(_ten_ops())
    runnables = {s.task_id: RunnableExecutionNode(spec=s, executor=ex) for s in specs}
    deps = dep_map_from_nodes(specs)
    status = {tid: NodeStatus.pending for tid in deps}
    outputs: dict[str, Any] = {}

    while any(st != NodeStatus.done for st in status.values()):
        for tid in ready_ids(specs, status):
            up = {d: outputs[d] for d in deps[tid]}
            outputs[tid] = runnables[tid].run({"upstream": up})
            status[tid] = NodeStatus.done

    assert outputs["n0"] == 1
    assert outputs["n3"] == 13
    assert outputs["n7"] == 81
    assert outputs["n9"] == 160
