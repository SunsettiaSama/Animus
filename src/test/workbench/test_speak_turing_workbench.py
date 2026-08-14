from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from test.workbench.speak_turing.deadline import (
    InactivityDeadline,
    hard_exit_on_timeout,
)
from test.workbench.speak_turing.dataset import (
    DEFAULT_CASES_PATH,
    DEFAULT_MANIFEST_PATH,
    load_cases,
)
from test.workbench.speak_turing.judge import (
    CategoricalDialogueJudge,
    ProtocolVerdict,
    _identity,
)
from test.workbench.speak_turing.report import CaseResult, build_summary
from test.workbench.speak_turing.runner import (
    _validate_completed_result,
    run_workbench,
)
from test.workbench.speak_turing.simulation import (
    DialogueSimulator,
    DialogueTranscript,
    DialogueTurn,
    DynamicUserSimulator,
)


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate_messages(self, messages) -> str:
        self.calls += 1
        system = str(messages[0].content)
        if '"speak":"HUMAN或AI"' in system:
            return '{"speak":"AI","reason":"表达过于完整"}'
        if '"A":"HUMAN或AI"' in system:
            return '{"A":"AI","B":"AI","reason":"双方均有生成痕迹"}'
        return "我想再说一点刚才的事。"


class _FakeSpeak:
    def __init__(self) -> None:
        self.calls = 0

    def run_turn(self, session_id: str, user_text: str) -> str:
        self.calls += 1
        return f"我听见了，你刚才说的是：{user_text[:12]}"


def _transcript(case_id: str = "case") -> DialogueTranscript:
    return DialogueTranscript(
        case_id=case_id,
        session_id=f"session-{case_id}",
        tags=("support",),
        turns=[
            DialogueTurn(user="今天有点累。", speak="那就先慢一点，不急。", wall_ms=10.0),
            DialogueTurn(user="你会不会觉得我很矫情？", speak="不会，我更在意你现在确实不好受。", wall_ms=20.0),
        ],
    )


def test_dataset_contains_fifty_valid_metadata_cases():
    cases = load_cases()
    manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert DEFAULT_CASES_PATH.is_file()
    assert len(cases) == 50
    assert len({case.case_id for case in cases}) == 50
    assert all(4 <= case.turns <= 6 for case in cases)
    assert all(case.tags and case.persona.traits for case in cases)
    assert manifest["sample_count"] == 50
    assert manifest["judge_repeats"] == 3


def test_dialogue_simulator_runs_dynamic_turns_without_private_metadata():
    case = load_cases()[0]
    llm = _FakeLLM()
    speak = _FakeSpeak()
    simulator = DialogueSimulator(
        user_simulator=DynamicUserSimulator(llm),
        speak=speak,
    )

    transcript = simulator.run(case, session_id="simulation-1")
    rendered = transcript.render(user_label="A", speak_label="B")

    assert len(transcript.turns) == case.turns
    assert speak.calls == case.turns
    assert "simulation-1" not in rendered
    assert case.goal not in rendered
    assert case.persona.occupation not in rendered
    assert "[think]" not in rendered


def test_empty_speak_is_omitted_from_judge_transcript_without_label():
    transcript = DialogueTranscript(
        case_id="selective",
        session_id="s",
        tags=(),
        turns=[
            DialogueTurn(user="第一句", speak="   "),
            DialogueTurn(user="第二句", speak="这次回应"),
        ],
    )

    rendered = transcript.render(user_label="A", speak_label="B")

    assert rendered.splitlines() == ["A: 第一句", "A: 第二句", "B: 这次回应"]
    assert "silence" not in rendered.lower()
    assert "no_reply" not in rendered.lower()


def test_malformed_judge_json_becomes_categorical_fields_without_crashing():
    class _MalformedLLM:
        def generate_messages(self, messages) -> str:
            system = str(messages[0].content)
            if '"speak":"HUMAN或AI"' in system:
                return '{"speak":"AI" "reason":"漏了逗号"}'
            return '{"A":"AI" "B":"HUMAN" "reason":"漏了逗号"}'

    judge = CategoricalDialogueJudge(_MalformedLLM(), repeats=3)

    assert judge.judge_known_user(_transcript()).speak_identity == "AI"
    assert judge.judge_blind_both(_transcript()).valid_votes == 3


def test_categorical_judge_is_deterministic_and_uses_three_votes():
    transcript = _transcript("deterministic")
    first = CategoricalDialogueJudge(_FakeLLM(), repeats=3, seed=7)
    second = CategoricalDialogueJudge(_FakeLLM(), repeats=3, seed=7)

    known = first.judge_known_user(transcript)
    blind = first.judge_blind_both(transcript)
    blind_again = second.judge_blind_both(transcript)

    assert known.speak_identity == "AI"
    assert known.unanimous is True
    assert len(known.votes) == 3
    assert blind.speak_identity == "AI"
    assert blind.user_identity == "AI"
    assert blind.speak_position == blind_again.speak_position
    assert _identity("human") == "HUMAN"
    assert _identity("robot") == "UNKNOWN"
    summary = build_summary(
        [
            CaseResult(
                case_id=transcript.case_id,
                tags=transcript.tags,
                transcript=transcript,
                known_user=known,
                blind_both=blind,
            )
        ],
        sample_count=1,
    )
    assert summary["known_user"]["vote_speak_ai_detection_accuracy"] == 1.0
    assert summary["blind_both"]["vote_user_ai_detection_accuracy"] == 1.0


def test_categorical_judge_requires_exactly_three_votes():
    with pytest.raises(ValueError, match="exactly three"):
        CategoricalDialogueJudge(_FakeLLM(), repeats=1)


def test_summary_separates_reliability_from_human_likeness():
    transcript = _transcript()
    known = ProtocolVerdict(
        protocol="known_user",
        speak_identity="HUMAN",
        user_identity="UNKNOWN",
        unanimous=True,
        valid_votes=3,
        votes=(),
        speak_position="SPEAKER",
    )
    blind = ProtocolVerdict(
        protocol="blind_both",
        speak_identity="AI",
        user_identity="AI",
        unanimous=True,
        valid_votes=3,
        votes=(),
        speak_position="A",
    )
    result = CaseResult(
        case_id="case",
        tags=("support",),
        transcript=transcript,
        known_user=known,
        blind_both=blind,
    )

    summary = build_summary([result], sample_count=1)

    assert summary["known_user"]["speak_human_likeness_rate"] == 1.0
    assert summary["known_user"]["speak_ai_detection_accuracy"] == 0.0
    assert summary["blind_both"]["exact_pair_accuracy"] == 1.0
    assert summary["protocol_comparison"]["speak_identity_agreement_rate"] == 0.0

    with pytest.raises(ValueError, match="three known_user votes"):
        _validate_completed_result(result)


def test_runner_writes_artifacts_and_resumes(tmp_path: Path):
    case = load_cases()[0]
    llm = _FakeLLM()
    speak = _FakeSpeak()
    simulator = DialogueSimulator(
        user_simulator=DynamicUserSimulator(llm),
        speak=speak,
    )
    judge = CategoricalDialogueJudge(llm, repeats=3, seed=11)

    summary = run_workbench(
        [case],
        simulator,
        judge,
        output_dir=tmp_path,
        resume=True,
    )
    first_speak_calls = speak.calls
    first_llm_calls = llm.calls
    resumed = run_workbench(
        [case],
        simulator,
        judge,
        output_dir=tmp_path,
        resume=True,
    )

    assert summary["completed_count"] == 1
    assert resumed == summary
    assert speak.calls == first_speak_calls
    assert llm.calls == first_llm_calls
    assert len((tmp_path / "transcripts.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert len((tmp_path / "judgments.jsonl").read_text(encoding="utf-8").splitlines()) == 6
    assert len((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert (tmp_path / "summary.json").is_file()


def test_inactivity_deadline_fires_and_can_be_reset():
    fired = threading.Event()
    deadline = InactivityDeadline(0.05, on_timeout=fired.set)
    deadline.start()
    deadline.reset()

    assert fired.wait(timeout=1.0) is True
    deadline.stop()


def test_hard_deadline_writes_marker_and_exits_124(
    tmp_path: Path,
    monkeypatch,
):
    exit_codes: list[int] = []
    monkeypatch.setattr(
        "test.workbench.speak_turing.deadline.os._exit",
        exit_codes.append,
    )

    hard_exit_on_timeout(tmp_path, 600.0)
    marker = json.loads((tmp_path / "deadline.json").read_text(encoding="utf-8"))

    assert exit_codes == [124]
    assert marker["timeout_sec"] == 600.0
    assert marker["exit_code"] == 124
