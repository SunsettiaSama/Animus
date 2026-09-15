"""拟人度管线测试：剧本库 / 模拟器 / 轨迹评委 / transcript 保证 / 写入-再检索。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evals.memory_humaneness.dialogue.judge_dialogue import (
    DIALOGUE_DIMENSIONS,
    ExpertDialogueJudge,
    HeuristicDialogueJudge,
    heuristic_dialogue_verdict,
)
from evals.memory_humaneness.dialogue.report_dialogue import write_dialogue_report
from evals.memory_humaneness.dialogue.scenarios import (
    Scenario,
    build_scenarios,
    load_scenarios,
    validate_scenarios,
)
from evals.memory_humaneness.dialogue.simulator import (
    DialogueSimulator,
    LLMUser,
    ScriptedUser,
)

SCENARIO_DATA = SRC / "evals/memory_humaneness/dialogue/data/scenarios.jsonl"


# ── 剧本库 ────────────────────────────────────────────────────────────────

def test_scenario_library_valid_and_persisted():
    scenarios = build_scenarios()
    assert len(scenarios) == 30
    assert validate_scenarios(scenarios) == []
    on_disk = load_scenarios(SCENARIO_DATA)
    assert [s.to_dict() for s in on_disk] == [s.to_dict() for s in scenarios]
    assert all(len(s.turns) >= 6 for s in scenarios)
    assert sum(len(s.callback_turns) for s in scenarios) >= 60  # 回调密度


# ── 模拟器 ────────────────────────────────────────────────────────────────

class _EchoAgentLLM:
    """确定性 Agent：从【相关记忆】取一行回填 + 每轮暗号（测写入-再检索）。"""

    def __init__(self):
        self.calls = 0

    def generate_messages(self, messages):
        self.calls += 1
        system = messages[0].content
        import re

        snippet = "没什么印象"
        if "【相关记忆】" in system:
            block = system.split("【相关记忆】", 1)[1]
            m = re.search(r"：(.+)", block)
            if m:
                snippet = m.group(1)[:20]
        return f"嗯，{snippet}。暗号{self.calls}号收到！"


def _stack_factory(tmp: Path):
    from evals.memory_humaneness.bases import StackMemoryBase

    return lambda: StackMemoryBase.build(jsonl_path=str(tmp / "dlg_stack.jsonl"))


def test_simulator_scripted_flow_and_transcript(tmp_path):
    sc = build_scenarios()[0]
    llm = _EchoAgentLLM()
    sim = DialogueSimulator(llm, transcript_path=tmp_path / "raw_llm.jsonl")
    factory = _stack_factory(tmp_path)
    base = factory()
    record = sim.run_scenario(sc, base, ScriptedUser(sc))

    assert record.error == ""
    assert len(record.turns) == len(sc.turns)
    assert all(t.agent for t in record.turns)
    assert llm.calls == len(sc.turns)
    # transcript：每轮回复原文（未剥 think 版本）先落盘
    items = [json.loads(l) for l in (tmp_path / "raw_llm.jsonl").open(encoding="utf-8")]
    assert len(items) == len(sc.turns)
    assert all(x["kind"] == "reply" for x in items)
    # encode 闭环：预载 + 每轮一条写回
    assert len(base.service) == len(sc.shared_memories) + len(sc.turns)


def test_write_then_read_within_trajectory(tmp_path):
    """中轮写入的事实，末轮可被检索到（多轮管线的核心价值）。"""
    from evals.memory_humaneness.bases import StackMemoryBase

    sc = Scenario(
        scenario_id="t", theme="测试", emotional_arc="-",
        shared_memories=[{"text": "用户养了叫雪球的仓鼠", "focus": "雪球",
                          "days_ago": 5, "emotion": "", "valence": "neutral"}],
        turns=["在吗", "我刚领养了一只猫，叫年糕", "没事，随便聊聊", "对了，我宠物们还好吗"],
    )
    sim = DialogueSimulator(_EchoAgentLLM())
    base = StackMemoryBase.build(jsonl_path=str(tmp_path / "w2r.jsonl"))
    record = sim.run_scenario(sc, base, ScriptedUser(sc))
    assert record.error == ""
    # 末轮检索应命中第 2 轮写入的"年糕"记忆
    block = base.recall("宠物 年糕 雪球", top_k=5)
    joined = " ".join(block.entries)
    assert "年糕" in joined


def test_llm_user_mode_uses_user_llm(tmp_path):
    sc = Scenario(
        scenario_id="t2", theme="测试", emotional_arc="-",
        shared_memories=[], turns=["a", "b"],
        user_brief_extra="你在加班",
    )

    class _FixedUserLLM:
        def __init__(self):
            self.calls = 0

        def generate_messages(self, messages):
            self.calls += 1
            # 用户侧输出带 think，也应被剥离
            return f"<think>用户视角</think>用户消息{self.calls}"

    user_llm = _FixedUserLLM()
    sim = DialogueSimulator(_EchoAgentLLM())
    from evals.memory_humaneness.bases import NullMemoryBase

    record = sim.run_scenario(sc, NullMemoryBase(), LLMUser(user_llm, sc, max_turns=2))
    assert record.error == ""
    assert [t.user for t in record.turns] == ["用户消息1", "用户消息2"]
    assert user_llm.calls == 2


# ── 轨迹评委 ──────────────────────────────────────────────────────────────

def _run_one(tmp_path, scenario) -> tuple:
    sim = DialogueSimulator(_EchoAgentLLM())
    base = _stack_factory(tmp_path)()
    record = sim.run_scenario(scenario, base, ScriptedUser(scenario))
    return record, scenario


def test_dialogue_judge_wrapped_json_and_raw_sink(tmp_path):
    record, sc = _run_one(tmp_path, build_scenarios()[0])
    saved = []
    judge = ExpertDialogueJudge(_GoodJudgeLLM(), raw_sink=saved.append)
    verdict = judge.judge(sc, record)
    assert verdict.judge == "llm_expert"
    assert verdict.scores["overall"] == pytest.approx(4.2)
    assert len(saved) == 1 and "scores" in saved[0]  # 原文在解析前已交给 sink


class _GoodJudgeLLM:
    def generate_messages(self, messages):
        return json.dumps({
            "scores": {"emotional_attunement": 4, "human_likeness": 4,
                       "memory_naturalness": 4, "initiative_rhythm": 4,
                       "overall": 4.2},
            "evidence": "末轮「谢啦」",
            "rationale": "跨轮承接自然。",
        }, ensure_ascii=False)


def test_dialogue_judge_salvage_and_fallback(tmp_path):
    record, sc = _run_one(tmp_path, build_scenarios()[1])

    class _BrokenQuote:
        def generate_messages(self, messages):
            return ('<think>…</think>{"scores": {"emotional_attunement": 4,'
                    '"human_likeness": 5, "memory_naturalness": 3,'
                    '"initiative_rhythm": 4, "overall": 4},'
                    '"evidence": "回复说"哈哈行"，自然。", "rationale": "口语。"}')

    v = ExpertDialogueJudge(_BrokenQuote()).judge(sc, record)
    assert v.judge == "llm_expert"
    assert v.rationale.startswith("[regex修复]")

    class _Garbage:
        def generate_messages(self, messages):
            return "完全不是 JSON"

    v2 = ExpertDialogueJudge(_Garbage()).judge(sc, record)
    assert v2.judge == "heuristic"
    assert 1.0 <= v2.scores["overall"] <= 5.0


def test_heuristic_dialogue_verdict_callback_bonus(tmp_path):
    """回调命中的轨迹，memory_naturalness 应高于不命中。"""
    from evals.memory_humaneness.dialogue.simulator import DialogueTurn

    sc = Scenario(
        scenario_id="t3", theme="t", emotional_arc="-",
        shared_memories=[{"text": "用户的橘猫蓝莓怕陌生人", "focus": "蓝莓",
                          "days_ago": 5, "emotion": "", "valence": "neutral"}],
        turns=["a", "b", "c", "d"],
        callback_turns={2: ["蓝莓"]},
    )

    def _record(agents: list[str]):
        from evals.memory_humaneness.dialogue.simulator import DialogueRecord

        return DialogueRecord(
            scenario_id="t3", theme="t", base="stack",
            turns=[DialogueTurn(index=i, user=sc.turns[i], agent=a)
                   for i, a in enumerate(agents)],
        )

    hit = heuristic_dialogue_verdict(sc, _record(["嗯", "哈", "蓝莓还是那么怕生啊", "嗯嗯"]))
    miss = heuristic_dialogue_verdict(sc, _record(["嗯", "哈", "没啥", "嗯嗯"]))
    assert hit.scores["memory_naturalness"] > miss.scores["memory_naturalness"]


# ── 端到端（报告）────────────────────────────────────────────────────────

def test_end_to_end_report(tmp_path):
    scenarios = build_scenarios()[:2]
    sim = DialogueSimulator(_EchoAgentLLM(), transcript_path=tmp_path / "raw.jsonl")
    records = []
    for sc in scenarios:
        for base in (_stack_factory(tmp_path)(),):
            r = sim.run_scenario(sc, base, ScriptedUser(sc))
            if not r.error:
                v = HeuristicDialogueJudge().judge(sc, r)
                r.judge = {"scores": v.scores, "evidence": "", "rationale": "",
                           "judge": v.judge}
            records.append(r)
    report = write_dialogue_report(records, tmp_path / "out", {"scenarios": 2})
    assert report.is_file()
    md = report.read_text(encoding="utf-8")
    assert "拟人度管线" in md and "stack" in md
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["stack"]["n"] == 2
    assert set(summary["stack"]["dimensions"]) == set(DIALOGUE_DIMENSIONS)
