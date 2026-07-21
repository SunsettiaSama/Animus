"""Rhythm pipeline unit tests.

Manual smoke (with a real SpeakService + LLM wired):
  python -c "from agent.soul.speak.service import SpeakService; ..."
  service.run_turn(sid, '在吗', pipeline='rhythm')          # speak path
  service.run_turn(sid, '先别回', pipeline='rhythm')         # listen/hold path
  service.run_turn(sid, '', mode='proactive', pipeline='rhythm')  # proactive
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from agent.soul.speak.io.outbound.stream import SpeakStreamChannel, SpeakStreamPipeline
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.pipelines.request_driven.orchestrator import SpeakPromptBundle
from agent.soul.speak.pipelines.rhythm.runner import RhythmPipelineRunner
from agent.soul.speak.pipelines.rhythm.state import RhythmStateStore
from agent.soul.speak.session.queue import UserInputItem


@dataclass
class _FakeLLM:
    replies: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def invoke(self, messages, **kwargs):
        del kwargs
        system = ""
        user = ""
        for msg in messages:
            role = getattr(msg, "type", None) or getattr(msg, "role", "")
            content = getattr(msg, "content", "")
            if role in ("system", "SystemMessage"):
                system = content
            else:
                user = content
        self.calls.append((system, user))
        text = self.replies.pop(0) if self.replies else "ok"
        return type("R", (), {"content": text})()


class _StubEngine(SpeakLLMEngine):
    def __init__(self, fake: _FakeLLM) -> None:
        super().__init__(llm=None)
        self._fake = fake

    @property
    def available(self) -> bool:
        return True

    def generate(self, user_text: str, *, system: str = "", context: str = ""):
        from agent.soul.speak.llm.engine import SpeakLLMResult

        del context
        self._fake.calls.append((system, user_text))
        text = self._fake.replies.pop(0) if self._fake.replies else "ok"
        return SpeakLLMResult(text=text)


def _director_factory(plan_gate: str):
    def generate(system: str, user: str) -> str:
        del user
        # Match unique system markers; ON_SCENE_SYSTEM also mentions 对话弧.
        if "开口指令中枢" in system:
            if plan_gate == "listen":
                return json.dumps(
                    {
                        "gate": "listen",
                        "mood": "先静",
                        "cue": "别开口",
                        "tempo": "收住",
                        "reply_guide": "别开口",
                        "share_tag": "none",
                        "reason": "fixture_listen",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "gate": "speak",
                    "mood": "想接住",
                    "cue": "回用户",
                    "tempo": "短句",
                    "reply_guide": "口语接话",
                    "share_tag": "none",
                    "reason": "fixture_speak",
                },
                ensure_ascii=False,
            )
        if "情感修正" in system:
            return json.dumps(
                {
                    "label": "接住当下",
                    "valence": "neutral",
                    "intensity": 0.3,
                    "reason": "fixture",
                },
                ensure_ascii=False,
            )
        if "刷新「临场状态」" in system:
            return json.dumps(
                {"on_scene": "还在对话里", "focus": "present"},
                ensure_ascii=False,
            )
        if "写一段「对话弧」" in system:
            return json.dumps({"arc": "先接住眼前输入，主动只提一件。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected director system: {system[:80]!r}")

    return generate


def _make_runner(*, gate: str, reply_text: str = "嗯，我在。") -> RhythmPipelineRunner:
    store = RhythmStateStore()
    fake = _FakeLLM(replies=[reply_text])
    channel = SpeakStreamChannel()
    pipeline = SpeakStreamPipeline(flush_mode="segment", emit_fn=channel.emit)
    llm = _StubEngine(fake)
    reply_calls: list[str] = []

    def compose_bundle(session_id: str, user_text: str, *, mode: str = "inbound"):
        del user_text
        return SpeakPromptBundle(session_id=session_id, mode=mode)

    def record_dialogue(session_id: str, user_text: str, agent_text: str):
        reply_calls.append(f"{session_id}:{user_text}:{agent_text}")

    runner = RhythmPipelineRunner(
        compose_bundle=compose_bundle,
        llm=llm,
        stream_pipeline=pipeline,
        outbound_stream=channel,
        rhythm_store=store,
        director_generate=_director_factory(gate),
        current_turn_index=lambda sid: 0,
        begin_turn=lambda sid: 1,
        record_dialogue=record_dialogue,
        peek_share=lambda sid: [],
        affect_every_k=99,
        on_scene_every_k=99,
    )
    runner._reply_calls = reply_calls  # type: ignore[attr-defined]
    runner._store = store  # type: ignore[attr-defined]
    return runner


def test_rhythm_runner_listen_does_not_call_reply_llm():
    runner = _make_runner(gate="listen")
    result = runner.run(
        UserInputItem(session_id="s1", user_text="先别回我", pipeline="rhythm")
    )
    assert result.answer == ""
    assert "rhythm_no_speak" in result.notes
    assert result.meta["gate"] == "listen"
    assert result.meta["pipeline"] == "rhythm"
    assert runner._reply_calls == []  # type: ignore[attr-defined]
    state = runner._store.session("s1")  # type: ignore[attr-defined]
    assert any(b.speaker == "user" and "先别回我" in b.text for b in state.history)


def test_rhythm_runner_speak_returns_answer_and_records():
    runner = _make_runner(
        gate="speak",
        reply_text="[speak]嗯，我在。[/speak][state]finish[/state]",
    )
    result = runner.run(
        UserInputItem(session_id="s1", user_text="在吗？", pipeline="rhythm", record=True)
    )
    assert "嗯，我在" in result.answer
    assert result.recorded
    assert result.meta["pipeline"] == "rhythm"
    assert result.meta["gate"] == "speak"
    assert "rhythm_plan" in result.meta
    assert runner._reply_calls  # type: ignore[attr-defined]


def test_rhythm_runner_proactive_mode_allowed_with_empty_user_text():
    runner = _make_runner(
        gate="speak",
        reply_text="[speak]忽然想起一件事。[/speak][state]finish[/state]",
    )
    result = runner.run(
        UserInputItem(
            session_id="s1",
            user_text="",
            mode="proactive",
            pipeline="rhythm",
            record=True,
        )
    )
    assert result.meta["trigger"] == "proactive"
    assert "忽然想起" in result.answer


def test_rhythm_runner_share_commits_only_after_speak():
    store = RhythmStateStore()
    queue = [
        {"item_id": "share-1", "topic": "边界草稿有重复"},
        {"item_id": "share-2", "topic": "先留冒烟入口"},
    ]
    fake = _FakeLLM(replies=["[speak]提一下草稿。[/speak][state]finish[/state]"])
    channel = SpeakStreamChannel()
    pipeline = SpeakStreamPipeline(flush_mode="segment", emit_fn=channel.emit)

    def director(system: str, user: str) -> str:
        del user
        if "开口指令中枢" in system:
            return json.dumps(
                {
                    "gate": "speak",
                    "mood": "想起一件",
                    "cue": "分享",
                    "tempo": "短句",
                    "reply_guide": "提一下草稿",
                    "share_tag": "share",
                    "share_id": "share-1",
                    "reason": "fixture_share",
                },
                ensure_ascii=False,
            )
        if "刷新「临场状态」" in system:
            return json.dumps(
                {"on_scene": "还在对话里", "focus": "present"},
                ensure_ascii=False,
            )
        if "写一段「对话弧」" in system:
            return json.dumps({"arc": "主动只提一件。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected director system: {system[:80]!r}")

    def pop_at(session_id: str, index: int):
        del session_id
        row = queue.pop(index)
        return type(
            "I",
            (),
            {
                "topic": row["topic"],
                "source": "",
                "salience": 0.0,
            },
        )()

    runner = RhythmPipelineRunner(
        compose_bundle=lambda sid, text, *, mode="inbound": SpeakPromptBundle(
            session_id=sid, mode=mode
        ),
        llm=_StubEngine(fake),
        stream_pipeline=pipeline,
        outbound_stream=channel,
        rhythm_store=store,
        director_generate=director,
        current_turn_index=lambda sid: 0,
        record_dialogue=lambda *a, **k: None,
        peek_share=lambda sid: list(queue),
        pop_share_at=pop_at,
        affect_every_k=99,
        on_scene_every_k=99,
    )
    result = runner.run(
        UserInputItem(session_id="s1", user_text="说说看", pipeline="rhythm")
    )
    assert result.answer
    assert len(queue) == 1
    assert queue[0]["item_id"] == "share-2"
    assert store.session("s1").last_shared_id == "share-1"


def test_rhythm_runner_listen_does_not_commit_share():
    store = RhythmStateStore()
    queue = [{"item_id": "share-1", "topic": "边界草稿有重复"}]
    channel = SpeakStreamChannel()
    pipeline = SpeakStreamPipeline(flush_mode="segment", emit_fn=channel.emit)

    def director(system: str, user: str) -> str:
        del user
        if "开口指令中枢" in system:
            return json.dumps(
                {
                    "gate": "listen",
                    "mood": "先静",
                    "cue": "别开口",
                    "tempo": "收住",
                    "reply_guide": "别开口",
                    "share_tag": "share",
                    "share_id": "share-1",
                    "reason": "fixture_listen_share",
                },
                ensure_ascii=False,
            )
        if "刷新「临场状态」" in system:
            return json.dumps(
                {"on_scene": "还在对话里", "focus": "present"},
                ensure_ascii=False,
            )
        if "写一段「对话弧」" in system:
            return json.dumps({"arc": "先听。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected director system: {system[:80]!r}")

    runner = RhythmPipelineRunner(
        compose_bundle=lambda sid, text, *, mode="inbound": SpeakPromptBundle(
            session_id=sid, mode=mode
        ),
        llm=_StubEngine(_FakeLLM()),
        stream_pipeline=pipeline,
        outbound_stream=channel,
        rhythm_store=store,
        director_generate=director,
        current_turn_index=lambda sid: 0,
        peek_share=lambda sid: list(queue),
        pop_share_at=lambda sid, idx: (_ for _ in ()).throw(
            AssertionError("listen must not pop share")
        ),
        affect_every_k=99,
        on_scene_every_k=99,
    )
    result = runner.run(
        UserInputItem(session_id="s1", user_text="先别说", pipeline="rhythm")
    )
    assert result.answer == ""
    assert "rhythm_no_speak" in result.notes
    assert len(queue) == 1
    assert store.session("s1").last_shared is None
