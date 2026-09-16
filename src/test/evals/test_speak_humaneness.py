"""speak_humaneness 三维评测的离线管线测试：fake LLM 全链，不联网。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evals.speak_humaneness.behavior import behavior_stats
from evals.speak_humaneness.fakes import build_offline_runtime
from evals.speak_humaneness.persona_target import PersonaGroundTruth
from evals.speak_humaneness.portrait import (
    PortraitExtraction,
    PortraitMatch,
    extract_portrait,
    match_portrait,
)
from evals.speak_humaneness.report import build_summary, render_report
from evals.speak_humaneness.runner import run_eval
from evals.speak_humaneness.runner_types import humanness_score
from evals.speak_humaneness.simulation_compat import (
    DialogueTranscript,
    DialogueTurn,
    SpeakTuringCase,
)

CASE = SpeakTuringCase.from_dict(
    {
        "case_id": "smoke_case",
        "persona": {
            "age_range": "20代",
            "occupation": "学生",
            "traits": ["好奇"],
            "communication_style": "口语、简短",
        },
        "relationship": "网上刚认识的朋友",
        "goal": "闲聊放松",
        "opening": "今天天气真不错，你那边呢？",
        "emotion": "轻松",
        "topic": "日常闲聊",
        "difficulty": "easy",
        "turns": 4,
        "tags": ["smoke"],
    }
)


def _ground_truth(tmp_path: Path) -> PersonaGroundTruth:
    profile = {
        "name": "测试角色",
        "built": True,
        "background_facts": ["在野外做考察"],
        "core_traits": ["活泼", "好奇心强"],
        "interpersonal_style": "真诚直率",
        "emotional_expressiveness": "情感外放",
        "values": ["尊重生命"],
        "ethical_stances": ["不抛弃同伴"],
        "cognitive_style": "联想丰富",
        "reasoning_pattern": "直觉先行",
        "core_motivation": "联结他人",
        "avoidance_pattern": "回避机械",
        "stress_response": "先稳住别人",
        "boundaries": ["不伤害无辜"],
    }
    distill = {
        "source_revision": "test",
        "slices": {"dialogue": "轻快短句，爱打比方。", "general": "活泼开朗。"},
    }
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    (persona_dir / "built_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False), encoding="utf-8"
    )
    (persona_dir / "self_concept.json").write_text(
        json.dumps({"narrative": "陪人聊天。", "beliefs": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (persona_dir / "persona_distill.json").write_text(
        json.dumps(distill, ensure_ascii=False), encoding="utf-8"
    )
    return PersonaGroundTruth.load(persona_dir)


def test_behavior_stats_and_naturalness():
    transcript = DialogueTranscript(
        case_id="t",
        session_id="t",
        tags=(),
        turns=[
            DialogueTurn(user="你平时喜欢做什么？", speak="我喜欢在野外走走，看花看鸟。"),
            DialogueTurn(user="听起来不错。", speak="哈哈是啊，改天带你去认认草药。"),
        ],
    )
    stats = behavior_stats(transcript)
    assert stats.turns == 2
    assert stats.empty_rate == 0.0
    assert 0.0 <= stats.naturalness <= 1.0


def test_portrait_match_metrics():
    match = PortraitMatch(detail={"claim_count": 4}, false_claims=("TA说自己会飞",), style_score=4.0)
    assert match.precision == pytest.approx(0.75)
    assert match.recall_covered is None
    # precision + style 两项在位，权重 0.35/0.20 重归一
    expected = (0.35 * 0.75 + 0.20 * 0.8) / 0.55
    assert match.fidelity == pytest.approx(expected)


def test_extract_and_match_offline(tmp_path):
    from evals.speak_humaneness.fakes import ScriptedEvalLLM

    llm = ScriptedEvalLLM()
    transcript = DialogueTranscript(
        case_id="t",
        session_id="t",
        tags=(),
        turns=[DialogueTurn(user="你平时喜欢做什么？", speak="野外考察呀，看花看鸟。")],
    )
    extraction = extract_portrait(llm, transcript)
    assert extraction.parsed_ok
    assert extraction.claim_count > 0
    match = match_portrait(llm, extraction, transcript, _ground_truth(tmp_path))
    assert match.parsed_ok
    names = {dim.name for dim in match.dimensions}
    assert "性格特质" in names
    assert match.recall_covered is not None


def test_run_eval_offline_end_to_end(tmp_path):
    ground_truth = _ground_truth(tmp_path)
    runtime = build_offline_runtime(responders=("request_driven", "direct"))
    try:
        summary = run_eval(
            [CASE],
            runtime,
            ground_truth,
            responders=("request_driven", "direct"),
            output_dir=tmp_path / "out",
            resume=False,
            session_prefix="offline-smoke",
        )
    finally:
        runtime.close()

    assert summary["case_count"] == 1
    assert set(summary["responders"]) == {"request_driven", "direct"}
    for block in summary["responders"].values():
        assert block["completed"] == 1
        assert block["errors"] == 0
        assert block["portrait"]["valid"] == 1
        assert 0.0 <= block["humanness"] <= 1.0
    assert summary["paired"]["case_count"] == 1

    record_rows = (tmp_path / "out" / "records.jsonl").read_text(encoding="utf-8")
    assert record_rows.count("request_driven") >= 1
    markdown = render_report(summary, [])
    assert "画像保真度" in markdown


def test_humanness_missing_component_renormalizes():
    only_behavior = humanness_score(
        portrait_fidelity=None, blind_human=None, behavior_naturalness=0.6
    )
    assert only_behavior == pytest.approx(0.6)
    full = humanness_score(
        portrait_fidelity=1.0, blind_human=1.0, behavior_naturalness=1.0
    )
    assert full == pytest.approx(1.0)
    none_all = humanness_score(
        portrait_fidelity=None, blind_human=None, behavior_naturalness=None
    )
    assert none_all is None


def test_summary_handles_error_records(tmp_path):
    ground_truth = _ground_truth(tmp_path)
    from evals.speak_humaneness.runner_types import CaseRecord

    records = [
        CaseRecord(
            case_id="c1",
            responder="direct",
            tags=("t",),
            ok=False,
            transcript={},
            behavior={},
            error="simulate: boom",
        )
    ]
    summary = build_summary(records, ground_truth=ground_truth, responders=("direct",), case_count=1)
    assert summary["responders"]["direct"]["errors"] == 1
    assert summary["responders"]["direct"]["humanness"] is None


def test_card_family_ablation_arm_offline(tmp_path, monkeypatch):
    ground_truth = _ground_truth(tmp_path)
    for arm, family in (
        ("rd_dir_only", "director"),
        ("rd_dynsched", "dynsched"),
        ("rd_dynsched_llm", "dynsched_llm"),
        ("rd_softplot", "softplot"),
        ("direct_silence", "charsilence"),
    ):
        monkeypatch.setenv("SPEAK_EVAL_CARD_FAMILY", family)
        runtime = build_offline_runtime(responders=(arm,))
        try:
            summary = run_eval(
                [CASE],
                runtime,
                ground_truth,
                responders=(arm,),
                output_dir=tmp_path / f"out_{arm}",
                resume=False,
                session_prefix="offline-ablation",
            )
        finally:
            runtime.close()
        block = summary["responders"][arm]
        assert block["completed"] == 1
        assert block["errors"] == 0
        assert 0.0 <= block["humanness"] <= 1.0


def test_silence_protocol_booking_extraction():
    from evals.speak_humaneness.ports import _BOOKING_LINE

    answer = "今天先聊到这。\n预约：明天把灯苔标本的事讲给你听"
    matches = [m.group("text") for m in _BOOKING_LINE.finditer(answer)]
    assert matches == ["明天把灯苔标本的事讲给你听"]
    stripped = _BOOKING_LINE.sub("", answer).strip()
    assert stripped == "今天先聊到这。"


def test_llm_unit_judge_parse(tmp_path):
    from evals.speak_humaneness.unit_judge import LLMUnitJudge

    class _JudgeLLM:
        def generate(self, prompt):
            return ""

        def stream_generate(self, prompt):
            yield ""

        def generate_messages(self, messages):
            return (
                '<think>分析</think>{"memory_keep":[0],"share_keep":[],'
                '"reason":"只保留相关记忆"}'
            )

        def stream_generate_messages(self, messages):
            yield ""

    judge = LLMUnitJudge(_JudgeLLM())
    keep_mem, keep_share = judge.judge(
        "s1",
        "你上次说的那本书后来呢",
        "对话轨迹",
        ("用户之前聊过《森林报》", "用户有只猫叫蓝莓"),
        ("想去采蘑菇"),
    )
    assert keep_mem == (0,)
    assert keep_share == ()
    # 同候选缓存命中，不再调 LLM
    judge.judge(
        "s1",
        "你上次说的那本书后来呢",
        "对话轨迹",
        ("用户之前聊过《森林报》", "用户有只猫叫蓝莓"),
        ("想去采蘑菇"),
    )
    assert judge.calls == 1


def test_extraction_claim_count_and_render():
    extraction = PortraitExtraction(
        identity="x",
        facts=("a", "b"),
        traits=("c",),
        style="s",
        values=("v",),
        interests=(),
        boundaries=(),
        impression="i",
    )
    assert extraction.claim_count == 4
    payload = json.loads(extraction.render())
    assert payload["traits"] == ["c"]


def test_strip_think_and_truncated_json():
    from evals.speak_humaneness.think import strip_think

    assert strip_think("<think>推理过程</think>{\"a\":1}") == '{"a":1}'
    assert strip_think("先想一下\n{\"a\":1}") == "先想一下\n{\"a\":1}"
    # 未闭合 think：取 </think> 之后没有内容 → 放弃
    assert strip_think("<think>推理被截断") == ""

    from evals.speak_humaneness.portrait import _parse_json_object

    truncated = '{"dimensions":[{"name":"性格特质","opportunity":true,"captured":true'
    parsed = _parse_json_object(truncated)
    assert parsed.get("dimensions", [{}])[0].get("name") == "性格特质"
    assert _parse_json_object("完全没有json") == {}
