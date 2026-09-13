"""L4 多跳记忆基准测试：生成器 / 校验 / 指标 / 转换。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evals.memory_humaneness.multihop import (
    MEMORIES_PER_CASE,
    MultihopCase,
    build_multihop_cases,
    evaluate_multihop_base,
    evaluate_multihop_case,
    to_humaneness_cases,
    validate_multihop,
)


# ── 生成器 ────────────────────────────────────────────────────────────────

def test_generator_builds_100_valid_deterministic_cases():
    cases = build_multihop_cases()
    assert len(cases) == 100
    assert validate_multihop(cases) == []
    # 确定性：同种子重建完全一致
    again = build_multihop_cases()
    assert [c.to_dict() for c in cases] == [c.to_dict() for c in again]
    # 三种模式均衡出现
    patterns = {c.pattern for c in cases}
    assert patterns == {"bridge", "constraint", "temporal"}
    for c in cases:
        assert len(c.memories) == MEMORIES_PER_CASE
        assert len(c.hops) == 2
        assert not c.answer_entities[0] or c.answer_entities[0] not in c.question


def test_validation_catches_corruptions():
    cases = build_multihop_cases(n=6)
    # 1) 问题泄漏答案
    bad = cases[0]
    person = bad.answer_entities[0]
    bad.question = f"{bad.question}{person}是谁来着？"
    assert any("泄漏答案实体" in p for p in validate_multihop(cases))
    # 2) 指纹碰撞：把跳指纹塞进另一条（干扰）记忆
    cases2 = build_multihop_cases(n=6)
    h = cases2[1].hops[0]
    for m in cases2[1].memories:
        if m["role"] == "distractor":
            m["text"] = m["text"] + h["key"]
            break
    assert any("跳指纹" in p for p in validate_multihop(cases2))
    # 3) 干扰项含答案实体
    cases3 = build_multihop_cases(n=6)
    ans = cases3[2].answer_entities[0]
    for m in cases3[2].memories:
        if m["role"] == "distractor":
            m["text"] = m["text"] + f"（顺带提到{ans}）"
            break
    assert any("干扰项" in p for p in validate_multihop(cases3))


# ── 检索指标（合成基座）──────────────────────────────────────────────────

class _ScriptedBase:
    """按脚本返回检索行的假基座，验证指标计算。"""

    kind = "scripted"

    def __init__(self, lines_by_q: dict[str, list[str]]) -> None:
        self.lines_by_q = lines_by_q
        self._ingested: list[str] = []

    def ingest(self, text: str, **kwargs) -> str:
        self._ingested.append(text)
        return f"id-{len(self._ingested)}"

    def recall(self, query: str, top_k: int = 5, emotional_context: str = ""):
        from agent.soul.memory.graph.networks.block import MemoryBlock

        return MemoryBlock(label="x", entries=self.lines_by_q.get(query, []))


def _first_case_with_lines():
    cases = build_multihop_cases(n=3)
    case = cases[0]
    hop_texts = [case.memories[h["memory_index"]]["text"] for h in case.hops]
    return case, hop_texts


def test_metrics_joint_hit_and_distractor_slots():
    case, hop_texts = _first_case_with_lines()
    noise = ["[干扰] 无关记忆一条", "[干扰] 无关记忆两条"]

    # 两跳都在场 → joint=True；2 条干扰占位
    lines = [hop_texts[0], noise[0], hop_texts[1], noise[1]]
    ev = evaluate_multihop_case(_ScriptedBase({case.question: lines}), case)
    assert ev["joint_hit"] is True
    assert ev["hop_ranks"] == [1, 3]
    assert ev["distractor_slots"] == 2

    # 只有一跳在场 → joint=False
    ev2 = evaluate_multihop_case(_ScriptedBase({case.question: [hop_texts[0], noise[0]]}), case)
    assert ev2["joint_hit"] is False
    assert ev2["hop_ranks"][1] == 0
    assert ev2["distractor_slots"] == 1

    # 实体共享的干扰项（含跳锚点但非跳文本）不算跳命中
    anchor = case.hops[0]["anchors"][0]
    ev3 = evaluate_multihop_case(
        _ScriptedBase({case.question: [f"[干扰] 又提到{anchor}的别的事", hop_texts[1]]}), case,
    )
    assert ev3["hop_ranks"][0] == 0


def test_evaluate_multihop_base_factory_mode_preloads():
    """工厂模式：预载全部 10 条后才检索（scripted 基座记录 ingest 数）。"""
    case, hop_texts = _first_case_with_lines()
    made = []

    def factory():
        base = _ScriptedBase({case.question: list(hop_texts)})
        made.append(base)
        return base

    result = evaluate_multihop_base(factory, [case])
    assert result["metrics"]["joint_hit_rate"] == 1.0
    assert made[0]._ingested and len(made[0]._ingested) == MEMORIES_PER_CASE


# ── 真实基座（确定性子集）────────────────────────────────────────────────

def test_real_stack_base_pattern_discrimination():
    """stack 词面检索的设计特性：bridge 联合命中 1.0、constraint 0.0（过敏原无词面桥）。"""
    from evals.memory_humaneness.bases import StackMemoryBase

    cases = [c for c in build_multihop_cases(n=30)][:30]
    by_pattern: dict[str, list] = {}
    for c in cases:
        by_pattern.setdefault(c.pattern, []).append(c)

    def run(subset):
        return evaluate_multihop_base(
            lambda: StackMemoryBase.build(jsonl_path=str(_tmp() / "s.jsonl")),
            subset,
        )["metrics"]

    bridge_m = run(by_pattern["bridge"][:5])
    constraint_m = run(by_pattern["constraint"][:5])
    assert bridge_m["joint_hit_rate"] == 1.0
    assert constraint_m["joint_hit_rate"] == 0.0


def test_real_full_base_all_present_with_noise():
    from evals.memory_humaneness.bases import FullMemoryBase

    cases = build_multihop_cases(n=3)
    m = evaluate_multihop_base(lambda: FullMemoryBase(), cases)["metrics"]
    assert m["joint_hit_rate"] == 1.0
    assert m["distractor_slots_avg"] == MEMORIES_PER_CASE - 2  # 8 条干扰全占位


def _tmp():
    import tempfile
    return Path(tempfile.mkdtemp(prefix="mh4_"))


# ── L3 转换 ───────────────────────────────────────────────────────────────

def test_to_humaneness_cases_wiring():
    cases = build_multihop_cases(n=3)
    h = to_humaneness_cases(cases)
    assert len(h) == 3
    assert all(c.category == "multi_hop" for c in h)
    assert all(len(c.memories) == MEMORIES_PER_CASE for c in h)
    # must_remember 覆盖跳锚点与答案实体（不在问句中的）
    for hc, mc in zip(h, cases):
        for a in mc.answer_entities:
            if a not in mc.question:
                assert a in hc.must_remember
        assert "多跳" in hc.note
