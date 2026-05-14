from __future__ import annotations

import pytest

from agent.flow.base.components import (
    ExecutionNodeSpec,
    MetadataLayer,
    node_specs_to_dag_edges,
    validate_node_graph_ids,
)


def test_execution_node_spec_composite() -> None:
    meta = MetadataLayer(task_id="a", depends_on=(), tags={"team": "core"})
    spec = ExecutionNodeSpec(metadata=meta)
    assert spec.task_id == "a"
    assert spec.depends_on == ()


def test_validate_node_graph_ids_ok() -> None:
    nodes = (
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="a")),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="b", depends_on=("a",))),
    )
    validate_node_graph_ids(nodes)
    edges = node_specs_to_dag_edges(nodes)
    assert edges["b"] == frozenset({"a"})


def test_validate_node_graph_ids_duplicate() -> None:
    nodes = (
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="x")),
        ExecutionNodeSpec(metadata=MetadataLayer(task_id="x")),
    )
    with pytest.raises(ValueError, match="duplicate"):
        validate_node_graph_ids(nodes)


def test_validate_node_graph_ids_unknown_dep() -> None:
    nodes = (ExecutionNodeSpec(metadata=MetadataLayer(task_id="a", depends_on=("ghost",))),)
    with pytest.raises(ValueError, match="unknown"):
        validate_node_graph_ids(nodes)
