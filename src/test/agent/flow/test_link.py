from __future__ import annotations

import pytest

from agent.flow.base import (
    ExecutionNodeSpec,
    MetadataLayer,
    NodeStatus,
    assert_acyclic,
    dep_map_from_nodes,
    index_nodes,
    layers,
    parallel_width,
    ready_ids,
    to_dag_specs,
)
from agent.flow.base.graph import has_cycle


def _a_b_chain() -> tuple[ExecutionNodeSpec, ...]:
    return (
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="a")),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="b", depends_on=("a",))),
    )


def test_dep_map_and_to_dag_specs() -> None:
    a, b = _a_b_chain()
    m = dep_map_from_nodes((a, b))
    assert m == {"a": frozenset(), "b": frozenset({"a"})}
    specs = to_dag_specs((a, b))
    assert len(specs) == 2
    assert all(st == NodeStatus.pending for _, _, st in specs)


def test_ready_ids_after_a_done() -> None:
    a, b = _a_b_chain()
    r = ready_ids((a, b), {a.task_id: NodeStatus.done})
    assert r == ["b"]


def test_parallel_width_and_layers() -> None:
    a, b = _a_b_chain()
    assert parallel_width((a, b)) == 1
    assert layers((a, b)) == [["a"], ["b"]]


def test_assert_acyclic_raises() -> None:
    nodes = (
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="x", depends_on=("y",))),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="y", depends_on=("x",))),
    )
    deps = dep_map_from_nodes(nodes)
    assert has_cycle(set(deps), deps) is True
    with pytest.raises(ValueError, match="cycle"):
        assert_acyclic(nodes)


def test_index_nodes() -> None:
    a, b = _a_b_chain()
    idx = index_nodes((a, b))
    assert idx["a"] is a and idx["b"] is b
