from __future__ import annotations

import pytest

from agent.flow.base import (
    NodeStatus,
    has_cycle,
    max_parallel_width,
    ready_node_ids,
    topological_layers,
    validate_known_dependencies,
)


def test_ready_node_ids_linear_chain() -> None:
    nodes = [
        ("a", frozenset(), NodeStatus.pending),
        ("b", frozenset({"a"}), NodeStatus.pending),
        ("c", frozenset({"b"}), NodeStatus.pending),
    ]
    assert ready_node_ids(nodes) == ["a"]
    nodes2 = [
        ("a", frozenset(), NodeStatus.done),
        ("b", frozenset({"a"}), NodeStatus.pending),
        ("c", frozenset({"b"}), NodeStatus.pending),
    ]
    assert ready_node_ids(nodes2) == ["b"]


def test_ready_node_ids_parallel_after_join() -> None:
    nodes = [
        ("a", frozenset(), NodeStatus.done),
        ("b", frozenset(), NodeStatus.done),
        ("c", frozenset({"a", "b"}), NodeStatus.pending),
    ]
    assert ready_node_ids(nodes) == ["c"]


def test_has_cycle_detects_loop() -> None:
    ids = {"a", "b"}
    deps = {"a": frozenset({"b"}), "b": frozenset({"a"})}
    assert has_cycle(ids, deps) is True


def test_has_cycle_acyclic() -> None:
    ids = {"a", "b", "c"}
    deps = {"a": frozenset(), "b": frozenset({"a"}), "c": frozenset({"a"})}
    assert has_cycle(ids, deps) is False


def test_validate_unknown_dependency() -> None:
    with pytest.raises(ValueError, match="unknown"):
        validate_known_dependencies({"a", "b"}, {"a": frozenset({"x"})})


def test_max_parallel_width_matches_document_semantics() -> None:
    ids = {"t1", "t2", "t3"}
    deps = {"t1": frozenset(), "t2": frozenset(), "t3": frozenset({"t1", "t2"})}
    assert max_parallel_width(ids, deps) == 2


def test_topological_layers() -> None:
    ids = {"t1", "t2", "t3"}
    deps = {"t1": frozenset(), "t2": frozenset({"t1"}), "t3": frozenset({"t1"})}
    assert topological_layers(ids, deps) == [["t1"], ["t2", "t3"]]
