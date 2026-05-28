"""Unit tests for AtomicReviewer and the AtomicPlanner+Reviewer integration."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from agent.flow.base.components.atomic_planner import AtomicPlanner, LlmCallFn
from agent.flow.base.components.atomic_reviewer import AtomicReviewer, _parse_outcome
from agent.flow.base.budget import DecompositionBudget, TopologyKind
from agent.flow.base.components.node_spec import NodeManifest, ReviewOutcome, TopologyDecision


# ── Helpers ───────────────────────────────────────────────────────────────────

DEFAULT_BUDGET    = DecompositionBudget(max_depth=3, max_width=8, max_atom_steps=5,
                                        max_review_rounds=1)
NO_REVIEW_BUDGET  = DecompositionBudget(max_depth=3, max_width=8, max_atom_steps=5,
                                         max_review_rounds=0)


def _composite_manifest(**kw) -> NodeManifest:
    defaults = dict(
        task_id="build_auth",
        description="Build full auth module",
        input_contract="",
        output_contract="",
    )
    defaults.update(kw)
    return NodeManifest(**defaults)


def _flat_decision() -> TopologyDecision:
    return TopologyDecision(
        kind=TopologyKind.flat,
        reason="two sub-tasks",
        sub_manifests=(
            NodeManifest(task_id="sub_a", description="A",
                         input_contract="in", output_contract="mid"),
            NodeManifest(task_id="sub_b", description="B",
                         depends_on=("sub_a",), input_contract="mid", output_contract="out"),
        ),
    )


def _approved_json() -> str:
    return json.dumps({"approved": True, "critique": "", "revised": None})


def _make_reviewer(llm_call: LlmCallFn | None = None) -> AtomicReviewer:
    return AtomicReviewer(llm_call=llm_call or (lambda s, u: _approved_json()))


def _make_planner(llm_call: LlmCallFn | None = None,
                  reviewer: AtomicReviewer | None = None) -> AtomicPlanner:
    _default_json = json.dumps({"kind": "atomic", "reason": "noop", "sub_nodes": []})
    return AtomicPlanner(
        llm_call=llm_call or (lambda s, u: _default_json),
        reviewer=reviewer,
    )


# ── DecompositionBudget.review_enabled ───────────────────────────────────────

def test_review_enabled_default():
    assert DecompositionBudget().review_enabled


def test_review_disabled_when_zero():
    assert not DecompositionBudget(max_review_rounds=0).review_enabled


def test_descend_preserves_max_review_rounds():
    b = DecompositionBudget(max_depth=3, max_review_rounds=2)
    child = b.descend()
    assert child.max_review_rounds == 2
    assert child.max_depth == 2


# ── _parse_outcome ────────────────────────────────────────────────────────────

def test_parse_outcome_approved():
    raw = json.dumps({"approved": True, "critique": "", "revised": None})
    o = _parse_outcome(raw, _flat_decision())
    assert o.approved
    assert o.revised is None


def test_parse_outcome_rejected_with_revision():
    revised_json = {
        "kind": "nested",
        "reason": "tightly coupled; prefer nested",
        "output_node_id": "sub_b",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "A",
             "depends_on": [], "input_contract": "in", "output_contract": "mid",
             "tool_package": None, "max_steps": 3},
            {"task_id": "sub_b", "description": "B",
             "depends_on": ["sub_a"], "input_contract": "mid", "output_contract": "out",
             "tool_package": None, "max_steps": 2},
        ],
    }
    raw = json.dumps({"approved": False, "critique": "should be nested", "revised": revised_json})
    o = _parse_outcome(raw, _flat_decision())
    assert not o.approved
    assert o.critique == "should be nested"
    assert o.revised is not None
    assert o.revised.kind == TopologyKind.nested
    assert o.revised.output_node_id == "sub_b"
    assert len(o.revised.sub_manifests) == 2


def test_parse_outcome_rejected_no_revision():
    raw = json.dumps({"approved": False, "critique": "cannot fix", "revised": None})
    o = _parse_outcome(raw, _flat_decision())
    assert not o.approved
    assert o.revised is None


def test_parse_outcome_unparseable_defaults_approved():
    o = _parse_outcome("not json at all", _flat_decision())
    assert o.approved


def test_parse_outcome_with_surrounding_prose():
    raw = json.dumps({"approved": True, "critique": "", "revised": None})
    o = _parse_outcome(f"Here is the review:\n{raw}\nEnd.", _flat_decision())
    assert o.approved


# ── AtomicReviewer.review ─────────────────────────────────────────────────────

def test_review_skipped_when_review_disabled():
    calls: list[str] = []
    reviewer = _make_reviewer(lambda s, u: (calls.append(u), _approved_json())[1])

    outcome = asyncio.get_event_loop().run_until_complete(
        reviewer.review(_composite_manifest(), _flat_decision(), NO_REVIEW_BUDGET)
    )

    assert len(calls) == 0
    assert outcome.approved


def test_review_calls_llm_and_returns_approved():
    calls: list[str] = []
    reviewer = _make_reviewer(lambda s, u: (calls.append(u), _approved_json())[1])

    outcome = asyncio.get_event_loop().run_until_complete(
        reviewer.review(_composite_manifest(), _flat_decision(), DEFAULT_BUDGET)
    )

    assert len(calls) == 1    # LLM was called once
    assert outcome.approved


def test_review_returns_revised_when_llm_rejects():
    nested_rev_json = {
        "kind": "nested",
        "reason": "prefer nested",
        "output_node_id": "sub_b",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "A",
             "depends_on": [], "input_contract": "in", "output_contract": "mid",
             "tool_package": None, "max_steps": 3},
            {"task_id": "sub_b", "description": "B",
             "depends_on": ["sub_a"], "input_contract": "mid", "output_contract": "out",
             "tool_package": None, "max_steps": 2},
        ],
    }
    reject_json = json.dumps({"approved": False, "critique": "io mismatch", "revised": nested_rev_json})
    reviewer = _make_reviewer(lambda s, u: reject_json)

    outcome = asyncio.get_event_loop().run_until_complete(
        reviewer.review(_composite_manifest(), _flat_decision(), DEFAULT_BUDGET)
    )

    assert not outcome.approved
    assert outcome.revised is not None
    assert outcome.revised.kind == TopologyKind.nested


# ── AtomicPlanner + AtomicReviewer integration ───────────────────────────────

def test_planner_uses_reviewer_approved_decision():
    """Reviewer approves �?planner's original decision used unchanged."""
    flat_json = json.dumps({
        "kind": "flat", "reason": "two sub-tasks", "output_node_id": "",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "A", "depends_on": [],
             "input_contract": "in", "output_contract": "out", "tool_package": None, "max_steps": 3},
        ],
    })
    reviewer = _make_reviewer(lambda s, u: _approved_json())
    planner  = _make_planner(lambda s, u: flat_json, reviewer=reviewer)

    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(_composite_manifest(), DEFAULT_BUDGET)
    )

    assert decision.kind == TopologyKind.flat


def test_planner_uses_revised_when_reviewer_rejects():
    """Reviewer rejects with revised �?revised decision used."""
    flat_json = json.dumps({
        "kind": "flat", "reason": "two sub-tasks", "output_node_id": "",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "A", "depends_on": [],
             "input_contract": "in", "output_contract": "out", "tool_package": None, "max_steps": 3},
        ],
    })
    nested_rev = {
        "kind": "nested", "reason": "prefer nested",
        "output_node_id": "sub_a",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "A", "depends_on": [],
             "input_contract": "in", "output_contract": "out", "tool_package": None, "max_steps": 3},
        ],
    }
    reject_json = json.dumps({"approved": False, "critique": "io mismatch", "revised": nested_rev})
    reviewer = _make_reviewer(lambda s, u: reject_json)
    planner  = _make_planner(lambda s, u: flat_json, reviewer=reviewer)

    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(_composite_manifest(), DEFAULT_BUDGET)
    )

    assert decision.kind == TopologyKind.nested


def test_planner_falls_back_to_atomic_when_reviewer_cannot_revise():
    """Reviewer rejects, no revision �?atomic fallback."""
    flat_json = json.dumps({
        "kind": "flat", "reason": "two sub-tasks", "output_node_id": "",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "A", "depends_on": [],
             "input_contract": "in", "output_contract": "out", "tool_package": None, "max_steps": 3},
        ],
    })
    no_fix_json = json.dumps({"approved": False, "critique": "unfixable", "revised": None})
    reviewer = _make_reviewer(lambda s, u: no_fix_json)
    planner  = _make_planner(lambda s, u: flat_json, reviewer=reviewer)

    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(_composite_manifest(), DEFAULT_BUDGET)
    )

    assert decision.kind == TopologyKind.atomic
    assert "reviewer rejected" in decision.reason
    assert "unfixable" in decision.reason


def test_planner_skips_review_when_budget_disables_it():
    """max_review_rounds=0 �?reviewer's LLM never called."""
    flat_json = json.dumps({
        "kind": "flat", "reason": "two sub-tasks", "output_node_id": "",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "A", "depends_on": [],
             "input_contract": "in", "output_contract": "out", "tool_package": None, "max_steps": 3},
        ],
    })
    reviewer_calls: list[str] = []
    reviewer = _make_reviewer(lambda s, u: (reviewer_calls.append(u), _approved_json())[1])
    planner  = _make_planner(lambda s, u: flat_json, reviewer=reviewer)

    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(_composite_manifest(), NO_REVIEW_BUDGET)
    )

    assert len(reviewer_calls) == 0
    assert decision.kind == TopologyKind.flat


def test_planner_skips_review_when_no_reviewer_set():
    flat_json = json.dumps({
        "kind": "flat", "reason": "two sub-tasks", "output_node_id": "",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "A", "depends_on": [],
             "input_contract": "in", "output_contract": "out", "tool_package": None, "max_steps": 3},
        ],
    })
    planner = _make_planner(lambda s, u: flat_json, reviewer=None)

    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(_composite_manifest(), DEFAULT_BUDGET)
    )

    assert decision.kind == TopologyKind.flat


def test_planner_set_reviewer_late_injection():
    planner  = _make_planner(reviewer=None)
    reviewer = _make_reviewer()
    planner.set_reviewer(reviewer)
    assert planner._reviewer is reviewer


# ── ReviewOutcome dataclass ───────────────────────────────────────────────────

def test_review_outcome_approved_fields():
    o = ReviewOutcome(approved=True)
    assert o.approved
    assert o.critique == ""
    assert o.revised is None


def test_review_outcome_rejected_fields():
    rev = TopologyDecision(kind=TopologyKind.atomic, reason="fallback")
    o = ReviewOutcome(approved=False, critique="bad io chain", revised=rev)
    assert not o.approved
    assert "io" in o.critique
    assert o.revised is rev
