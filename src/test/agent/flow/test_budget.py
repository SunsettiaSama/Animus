"""Unit tests for DecompositionBudget, TopologyKind, and is_atomic()."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from agent.flow.base.budget import DecompositionBudget, TopologyKind, is_atomic
from agent.flow.base.components.node_spec import NodeManifest


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _manifest(**kwargs) -> NodeManifest:
    defaults = dict(
        task_id="test_node",
        description="Do something",
        input_contract="A string input",
        output_contract="A string output",
        max_steps=3,
    )
    defaults.update(kwargs)
    return NodeManifest(**defaults)


DEFAULT_BUDGET = DecompositionBudget(max_depth=3, max_width=8, max_atom_steps=5)


# ── DecompositionBudget ───────────────────────────────────────────────────────

def test_budget_defaults():
    b = DecompositionBudget()
    assert b.max_depth == 3
    assert b.max_width == 8
    assert b.max_atom_steps == 5
    assert not b.exhausted


def test_budget_exhausted_at_zero():
    b = DecompositionBudget(max_depth=0)
    assert b.exhausted


def test_budget_descend_reduces_depth():
    b = DecompositionBudget(max_depth=3, max_width=6, max_atom_steps=4)
    child = b.descend()
    assert child.max_depth == 2
    assert child.max_width == 6       # width preserved
    assert child.max_atom_steps == 4  # atom_steps preserved


def test_budget_descend_clamps_at_zero():
    b = DecompositionBudget(max_depth=0)
    child = b.descend()
    assert child.max_depth == 0
    assert child.exhausted


def test_budget_descend_chain():
    b = DecompositionBudget(max_depth=3)
    assert b.descend().descend().descend().exhausted


# ── TopologyKind ──────────────────────────────────────────────────────────────

def test_topology_kind_values():
    assert TopologyKind.atomic.value == "atomic"
    assert TopologyKind.flat.value == "flat"
    assert TopologyKind.nested.value == "nested"


def test_topology_kind_from_string():
    assert TopologyKind("flat") is TopologyKind.flat


# ── is_atomic ─────────────────────────────────────────────────────────────────

def test_is_atomic_budget_exhausted_forces_true():
    """Exhausted budget always returns True regardless of manifest content."""
    m = _manifest(input_contract="", output_contract="", max_steps=100)
    assert is_atomic(m, DecompositionBudget(max_depth=0))


def test_is_atomic_clear_io_and_steps():
    m = _manifest(input_contract="user query string", output_contract="answer string", max_steps=3)
    assert is_atomic(m, DEFAULT_BUDGET)


def test_is_atomic_missing_input_contract():
    m = _manifest(input_contract="", output_contract="answer string", max_steps=3)
    assert not is_atomic(m, DEFAULT_BUDGET)


def test_is_atomic_missing_output_contract():
    m = _manifest(input_contract="user query", output_contract="", max_steps=3)
    assert not is_atomic(m, DEFAULT_BUDGET)


def test_is_atomic_steps_at_limit():
    m = _manifest(max_steps=5)
    assert is_atomic(m, DEFAULT_BUDGET)  # 5 == max_atom_steps


def test_is_atomic_steps_exceed_limit():
    m = _manifest(max_steps=6)
    assert not is_atomic(m, DEFAULT_BUDGET)


def test_is_atomic_no_max_steps_declared():
    """No max_steps �?doesn't fail the step check, other conditions decide."""
    m = _manifest(max_steps=None)
    assert is_atomic(m, DEFAULT_BUDGET)


def test_is_atomic_composite_keyword_cn():
    m = _manifest(description="写用户登录逻辑并且写注册逻辑以及密码重置")
    assert not is_atomic(m, DEFAULT_BUDGET)


def test_is_atomic_composite_keyword_en():
    m = _manifest(description="Write login handler and also write registration handler")
    assert not is_atomic(m, DEFAULT_BUDGET)


def test_is_atomic_already_has_sub_manifests():
    """If sub_manifests already present, node is treated as atomic (container)."""
    sub = _manifest(task_id="sub_a", description="sub task")
    m = NodeManifest(
        task_id="parent",
        description="parent",
        input_contract="in",
        output_contract="out",
        sub_manifests=(sub,),
    )
    assert is_atomic(m, DEFAULT_BUDGET)


def test_is_atomic_description_only_composite_keyword_at_word_boundary():
    """Keyword must appear as a substring; partial matches don't count."""
    m = _manifest(description="Handle additionally complex scenario")
    # 'additionally' contains 'additionally' which is in _COMPOSITE_KEYWORDS
    assert not is_atomic(m, DEFAULT_BUDGET)
