"""Unit tests for AtomicPlanner with injected LlmCallFn (no LLM/langchain needed)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from agent.flow.base.components.atomic_planner import AtomicPlanner, LlmCallFn, _parse_decision
from agent.flow.base.budget import DecompositionBudget, TopologyKind
from agent.flow.base.components.node_spec import NodeManifest, TopologyDecision


# ── Helpers ───────────────────────────────────────────────────────────────────

DEFAULT_BUDGET = DecompositionBudget(max_depth=3, max_width=8, max_atom_steps=5)
TIGHT_BUDGET   = DecompositionBudget(max_depth=0)


def _atomic_manifest(**kw) -> NodeManifest:
    defaults = dict(
        task_id="validate_email",
        description="Validate email format",
        input_contract="raw email string",
        output_contract="boolean is_valid",
        max_steps=3,
    )
    defaults.update(kw)
    return NodeManifest(**defaults)


def _composite_manifest(**kw) -> NodeManifest:
    defaults = dict(
        task_id="build_auth",
        description="Build full authentication module",
        input_contract="",
        output_contract="",
        max_steps=None,
    )
    defaults.update(kw)
    return NodeManifest(**defaults)


def _noop_llm_call(system: str, user: str) -> str:
    """LlmCallFn stub that returns an atomic decision JSON."""
    return json.dumps({"kind": "atomic", "reason": "stub", "sub_nodes": []})


def _make_planner(llm_call: LlmCallFn | None = None) -> AtomicPlanner:
    return AtomicPlanner(llm_call=llm_call or _noop_llm_call)


# ── _parse_decision ───────────────────────────────────────────────────────────

def test_parse_decision_atomic():
    raw = json.dumps({"kind": "atomic", "reason": "clear I/O", "sub_nodes": []})
    d = _parse_decision(raw, _atomic_manifest())
    assert d.kind == TopologyKind.atomic
    assert d.reason == "clear I/O"
    assert d.sub_manifests == ()


def test_parse_decision_flat():
    raw = json.dumps({
        "kind": "flat",
        "reason": "three independent sub-tasks",
        "output_node_id": "",
        "sub_nodes": [
            {"task_id": "sub_a", "description": "Do A",
             "depends_on": [], "input_contract": "x", "output_contract": "y",
             "tool_package": None, "max_steps": 3},
            {"task_id": "sub_b", "description": "Do B",
             "depends_on": ["sub_a"], "input_contract": "y", "output_contract": "z",
             "tool_package": "code", "max_steps": 4},
        ],
    })
    d = _parse_decision(raw, _composite_manifest())
    assert d.kind == TopologyKind.flat
    assert len(d.sub_manifests) == 2
    assert d.sub_manifests[0].task_id == "sub_a"
    assert d.sub_manifests[1].depends_on == ("sub_a",)
    assert d.sub_manifests[1].tool_package == "code"


def test_parse_decision_nested_with_exit():
    raw = json.dumps({
        "kind": "nested",
        "reason": "self-contained module",
        "output_node_id": "auth_exit",
        "sub_nodes": [
            {"task_id": "auth_core",  "description": "Core auth",
             "depends_on": [], "input_contract": "creds", "output_contract": "token",
             "tool_package": None, "max_steps": 5},
            {"task_id": "auth_exit", "description": "Auth middleware",
             "depends_on": ["auth_core"], "input_contract": "token", "output_contract": "middleware",
             "tool_package": None, "max_steps": 3},
        ],
    })
    d = _parse_decision(raw, _composite_manifest())
    assert d.kind == TopologyKind.nested
    assert d.output_node_id == "auth_exit"
    assert len(d.sub_manifests) == 2


def test_parse_decision_with_json_noise():
    payload = json.dumps({"kind": "atomic", "reason": "ok", "sub_nodes": []})
    raw = f"Here is my decision:\n{payload}\nThanks."
    d = _parse_decision(raw, _atomic_manifest())
    assert d.kind == TopologyKind.atomic


# ── AtomicPlanner.assess �?fast paths (no LLM) ───────────────────────────────

def test_assess_skips_llm_when_is_atomic():
    calls: list[str] = []

    def _tracking(system, user):
        calls.append(user)
        return json.dumps({"kind": "atomic", "reason": "stub", "sub_nodes": []})

    planner = _make_planner(_tracking)
    manifest = _atomic_manifest()

    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(manifest, DEFAULT_BUDGET)
    )

    assert len(calls) == 0   # LLM never called for atomic manifests
    assert decision.kind == TopologyKind.atomic


def test_assess_returns_atomic_when_budget_exhausted():
    calls: list[str] = []

    def _tracking(system, user):
        calls.append(user)
        return json.dumps({"kind": "atomic", "reason": "stub", "sub_nodes": []})

    planner = _make_planner(_tracking)
    manifest = _composite_manifest()

    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(manifest, TIGHT_BUDGET)
    )

    assert len(calls) == 0   # budget exhausted �?no LLM
    assert decision.kind == TopologyKind.atomic


# ── AtomicPlanner.assess �?LLM routing ───────────────────────────────────────

def test_assess_calls_llm_and_returns_flat():
    flat_json = json.dumps({
        "kind": "flat",
        "reason": "two independent sub-tasks",
        "output_node_id": "",
        "sub_nodes": [
            {"task_id": "sub_login", "description": "Login logic",
             "depends_on": [], "input_contract": "creds", "output_contract": "session",
             "tool_package": None, "max_steps": 3},
            {"task_id": "sub_register", "description": "Register logic",
             "depends_on": [], "input_contract": "user_data", "output_contract": "user_id",
             "tool_package": None, "max_steps": 3},
        ],
    })

    planner = _make_planner(lambda s, u: flat_json)
    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(_composite_manifest(), DEFAULT_BUDGET)
    )

    assert decision.kind == TopologyKind.flat
    assert len(decision.sub_manifests) == 2
    assert decision.sub_manifests[0].task_id == "sub_login"


def test_assess_calls_llm_and_returns_nested():
    nested_json = json.dumps({
        "kind": "nested",
        "reason": "self-contained subsystem",
        "output_node_id": "auth_exit",
        "sub_nodes": [
            {"task_id": "auth_core", "description": "Core",
             "depends_on": [], "input_contract": "in", "output_contract": "out",
             "tool_package": None, "max_steps": 4},
            {"task_id": "auth_exit", "description": "Exit",
             "depends_on": ["auth_core"], "input_contract": "out", "output_contract": "mw",
             "tool_package": None, "max_steps": 2},
        ],
    })

    planner = _make_planner(lambda s, u: nested_json)
    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(_composite_manifest(), DEFAULT_BUDGET)
    )

    assert decision.kind == TopologyKind.nested
    assert decision.output_node_id == "auth_exit"
    assert len(decision.sub_manifests) == 2


def test_assess_width_overflow_promoted_to_nested():
    """When LLM returns more sub_nodes than max_width, flat �?nested."""
    narrow_budget = DecompositionBudget(max_depth=3, max_width=2, max_atom_steps=5)
    sub_nodes = [
        {"task_id": f"sub_{i}", "description": f"Step {i}",
         "depends_on": [] if i == 0 else [f"sub_{i-1}"],
         "input_contract": "x", "output_contract": "y",
         "tool_package": None, "max_steps": 2}
        for i in range(3)
    ]
    too_wide_json = json.dumps({
        "kind": "flat", "reason": "too many steps", "output_node_id": "",
        "sub_nodes": sub_nodes,
    })

    planner = _make_planner(lambda s, u: too_wide_json)
    decision = asyncio.get_event_loop().run_until_complete(
        planner.assess(_composite_manifest(), narrow_budget)
    )

    assert decision.kind == TopologyKind.nested
    assert "exceeded max_width" in decision.reason


# ── TopologyDecision.apply_to ─────────────────────────────────────────────────

def test_topology_decision_apply_to():
    sub = NodeManifest(task_id="child", description="child task")
    decision = TopologyDecision(
        kind=TopologyKind.flat,
        reason="two steps",
        sub_manifests=(sub,),
        output_node_id="",
    )
    base = NodeManifest(task_id="parent", description="parent task")
    updated = decision.apply_to(base)

    assert updated.task_id == "parent"
    assert updated.topology == TopologyKind.flat
    assert updated.topology_reason == "two steps"
    assert len(updated.sub_manifests) == 1
    assert updated.sub_manifests[0].task_id == "child"
