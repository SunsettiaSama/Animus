from __future__ import annotations

from agent.soul.speak.session.silence_policy import (
    ELLIPSIS_SPEAK,
    apply_empty_speak_policy,
    roll_empty_speak_policy,
)


def test_roll_empty_speak_policy_deterministic():
    assert roll_empty_speak_policy(rng=lambda: 0.0) == "ellipsis"
    assert roll_empty_speak_policy(rng=lambda: 0.99) == "hidden"


def test_apply_empty_speak_hidden():
    class _Pipeline:
        def _flush_channels(self):
            raise AssertionError("hidden should not flush")

    policy, answer, events = apply_empty_speak_policy(
        session_id="s1",
        pipeline=_Pipeline(),  # type: ignore[arg-type]
        stream=True,
        policy="hidden",
    )
    assert policy == "hidden"
    assert answer == ""
    assert events == []


def test_apply_empty_speak_ellipsis():
    from agent.soul.speak.io.outbound.stream.pipeline import SpeakStreamPipeline

    emitted: list[tuple[str, object]] = []

    def _emit(session_id: str, event: object) -> None:
        emitted.append((session_id, event))

    pipeline = SpeakStreamPipeline(emit_fn=_emit)
    policy, answer, events = apply_empty_speak_policy(
        session_id="s1",
        pipeline=pipeline,
        stream=True,
        policy="ellipsis",
    )
    assert policy == "ellipsis"
    assert answer == ELLIPSIS_SPEAK
    assert events
    assert any(getattr(e, "kind", "") == "speak" for e in events)
