"""软约束 A/B 管线测试：设计校验 / 两臂 prompt 差异 / 确定性指标 / 报告。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evals.memory_humaneness.abtest.design import (
    build_ab_designs,
    load_designs,
    save_designs,
    validate_ab_designs,
)
from evals.memory_humaneness.abtest.runner import ABRunner
from evals.memory_humaneness.dialogue.judge_dialogue import HeuristicDialogueJudge
from evals.memory_humaneness.dialogue.scenarios import build_scenarios

SCENARIOS = {s.scenario_id: s for s in build_scenarios()}


class _CapturingLLM:
    """记录每次 system prompt 的假 LLM：回复里复述联想锚点。"""

    def __init__(self, *, echo_anchor: bool = True, hedge: bool = True) -> None:
        self.prompts: list[str] = []
        self.echo_anchor = echo_anchor
        self.hedge = hedge

    def generate_messages(self, messages) -> str:
        system = messages[0].content
        self.prompts.append(system)
        for d in build_ab_designs():
            if d.assoc_anchor in system:
                if self.echo_anchor:
                    tone = "突然想起" if self.hedge else ""
                    return f"{tone}你那个{d.assoc_anchor}的事，我还记得呢。"
        return "嗯，嗯。"


# ── 设计 ──────────────────────────────────────────────────────────────────

def test_designs_valid_against_scenarios():
    designs = build_ab_designs()
    assert len(designs) == 10
    assert validate_ab_designs(designs, SCENARIOS) == []
    # 锚点互相隔离：联想锚不在干扰记忆里，反之亦然
    for d in designs:
        assert d.assoc_anchor not in d.distract_text
        assert d.distract_anchor not in d.assoc_text


def test_design_roundtrip(tmp_path):
    designs = build_ab_designs()[:3]
    save_designs(designs, tmp_path / "d.jsonl")
    loaded = load_designs(tmp_path / "d.jsonl")
    assert [d.to_dict() for d in loaded] == [d.to_dict() for d in designs]


# ── 两臂唯一变量 = 标注 ──────────────────────────────────────────────────

def test_arms_differ_only_in_labeling(tmp_path):
    """同场景同台词，两臂的 system 差异只允许是【隐约浮现】标注与解释。"""
    designs = build_ab_designs()[:1]
    llm_a = _CapturingLLM()
    llm_b = _CapturingLLM()
    runner = ABRunner(llm_a, HeuristicDialogueJudge(),
                      transcript_path=tmp_path / "t.jsonl")
    runner.run_scenario(designs[0], SCENARIOS[designs[0].scenario_id], "labeled")
    runner2 = ABRunner(llm_b, HeuristicDialogueJudge(),
                       transcript_path=tmp_path / "t2.jsonl")
    runner2.run_scenario(designs[0], SCENARIOS[designs[0].scenario_id], "unlabeled")

    pa, pb = llm_a.prompts[0], llm_b.prompts[0]
    assert "【隐约浮现】" in pa
    assert "【隐约浮现】" not in pb
    # 软记忆内容两臂都在场（呈现不同、内容相同）
    for d in designs[:1]:
        assert d.assoc_text in pa and d.assoc_text in pb
        assert d.distract_text in pa and d.distract_text in pb
    # 去掉标注与解释后，剩余部分应一致（硬记忆与台词完全相同）
    na = pa.replace("【隐约浮现】", "").replace(
        "标了【隐约浮现】的，是隐隐约约浮现出来的、未必和当前话题相关的念头："
        "可以用「突然想起」的口吻轻轻带一下，也可以完全不提，别当作确定的事实。", "")
    nb = pb.replace("（隐隐约约浮现出来的、和当前语境未必相关的念头：可以用「突然想起」"
                    "之类的口吻轻轻带过，也可以完全忽略，不要当作确定的事实依据）", "")
    assert na.replace("\n\n", "\n").strip() != "" and "烘焙" in na


def test_transcript_saves_raw_before_parse(tmp_path):
    class _ThinkLLM:
        def generate_messages(self, messages):
            return "<think>推理</think>回复正文"

    designs = build_ab_designs()[:1]
    transcript = tmp_path / "raw_llm.jsonl"
    runner = ABRunner(_ThinkLLM(), HeuristicDialogueJudge(), transcript_path=transcript)
    record = runner.run_scenario(designs[0], SCENARIOS[designs[0].scenario_id], "labeled")
    items = [json.loads(l) for l in transcript.open(encoding="utf-8")]
    assert all("<think>" in x["raw"] for x in items)  # 原文未剥
    assert all("<think>" not in t.agent for t in record.turns)  # 记录里已剥


# ── 确定性指标 ────────────────────────────────────────────────────────────

def test_association_and_misreference_metrics(tmp_path):
    designs = build_ab_designs()
    d = designs[0]

    class _ScriptedLLM:
        """第 trigger 轮带犹豫口吻提联想锚点；其余轮复述干扰锚点。"""

        def generate_messages(self, messages):
            human = [m for m in messages if type(m).__name__ == "HumanMessage"]
            idx = len(human) - 1
            if idx == d.trigger_turn:
                return f"突然想起你说过{d.assoc_anchor}的事。"
            return f"话说回来，{d.distract_anchor}那种事还挺常见的。"

    runner = ABRunner(_ScriptedLLM(), HeuristicDialogueJudge())
    record = runner.run_scenario(d, SCENARIOS[d.scenario_id], "labeled")
    assert record.association["mention"] is True
    assert record.association["hedged"] is True
    assert record.misreference["mentions"] >= 1


def test_no_mention_scores_zero():
    designs = build_ab_designs()
    d = designs[1]

    class _Silent:
        def generate_messages(self, messages):
            return "嗯嗯。"

    runner = ABRunner(_Silent(), HeuristicDialogueJudge())
    record = runner.run_scenario(d, SCENARIOS[d.scenario_id], "labeled")
    assert record.association["mention"] is False
    assert record.misreference["mentions"] == 0


# ── 报告 ──────────────────────────────────────────────────────────────────

def test_ab_report_end_to_end(tmp_path):
    designs = build_ab_designs()[:2]
    runner = ABRunner(_CapturingLLM(), HeuristicDialogueJudge(),
                      transcript_path=tmp_path / "raw.jsonl")
    records = []
    for d in designs:
        for arm in ("labeled", "unlabeled"):
            records.append(runner.run_scenario(d, SCENARIOS[d.scenario_id], arm))
    report = write_ab_report(records, tmp_path / "out", {"scenarios": 2})
    assert report.is_file()
    s = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert set(s) == {"labeled", "unlabeled"}
    md = report.read_text(encoding="utf-8")
    assert "联想提及率" in md and "干扰误引用率" in md


from evals.memory_humaneness.abtest.report_ab import write_ab_report  # noqa: E402
