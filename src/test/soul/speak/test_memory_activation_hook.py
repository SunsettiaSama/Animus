from __future__ import annotations

from agent.soul.speak.session.lifecycle import SpeakSessionRegistry
from agent.soul.speak.session.turn import SessionTurnHost, run_session_turn


class _FakeManager:
    def open(self, session_id: str, trigger: str = ""):
        from types import SimpleNamespace

        return SimpleNamespace(notes=[])

    def begin_push(self, session_id: str, user_text: str) -> None:
        pass

    def end_push(self, session_id: str, *, partial_output: str = "") -> None:
        pass

    def update_partial_output(self, session_id: str, partial: str) -> None:
        pass

    def record_turn(self, chunk, on_after=None):
        from types import SimpleNamespace

        return SimpleNamespace(recorded=True, notes=[])


def test_memory_activation_hook_fires_before_compose():
    calls: list[tuple[str, str, str]] = []
    compose_calls: list[str] = []

    def _activate(session_id: str, interactor_id: str, user_text: str) -> None:
        calls.append((session_id, interactor_id, user_text))

    def _compose(session_id: str, user_text: str, *, mode="inbound"):
        compose_calls.append(user_text)
        from types import SimpleNamespace

        return SimpleNamespace(user_text=user_text, build_system=lambda: "sys")

    registry = SpeakSessionRegistry()
    registry.bind_interactor("s1", "alice")

    host = SessionTurnHost(
        compose_bundle=_compose,
        llm=object(),
        stream_pipeline=object(),
        outbound_stream=object(),
        record_turn=lambda chunk: None,
        schedule_compose=lambda sid: None,
        on_memory_activation=_activate,
        resolve_interactor_id=registry.get_interactor,
    )

    class _HostStream:
        def begin_session(self, session_id: str) -> None:
            pass

    host.outbound_stream = _HostStream()

    class _LLM:
        def generate(self, user_text, system=""):
            from types import SimpleNamespace

            return SimpleNamespace(text="[think]x[/think][state:finish]ok")

    host.llm = _LLM()

    class _Pipeline:
        def emit_parsed_output(self, session_id, answer):
            return []

    host.stream_pipeline = _Pipeline()

    run_session_turn(_FakeManager(), host, "s1", "你好", record=False)

    assert calls == [("s1", "alice", "你好")]
    assert compose_calls == ["你好"]
