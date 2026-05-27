from __future__ import annotations

from typing import Any, Callable, Generator

from .tao import TaoEvent, TaoLoop


class ConvLoop:
    """
    Outer conversation loop — manages multi-turn sessions over TaoLoop.

    Responsibilities:
    - Wrap the inner TAO (Thought-Action-Observation) loop.
    - Restore PromptManager history when resuming a saved conversation,
      so the agent retains full context across page reloads.
    - Expose the same stream() / reset() interface as TaoLoop.
    """

    def __init__(self, tao: TaoLoop) -> None:
        self._tao = tao

    @property
    def tao_loop(self) -> TaoLoop:
        """Inner TAO engine (lifecycle, benchmark, shutdown close)."""

        return self._tao

    @property
    def medium_term(self) -> Any:
        return self._tao._medium_term

    def abort(self) -> None:
        self._tao.abort()

    def resolve_approval(self, request_id: str, approved: bool) -> bool:
        return self._tao.resolve_approval(request_id, approved)

    def rollback_unfinished_turn(self) -> None:
        self._tao.rollback_turn()

    @property
    def abort_signaled(self) -> bool:
        return self._tao._stop_event.is_set()

    def clear_persistent_memory(self) -> None:
        self._tao.clear_memory()

    @property
    def persona_enabled(self) -> bool:
        return self._tao._persona is not None

    def clear_persona(self) -> None:
        self._tao.clear_persona()

    def read_timeline(self, date: str | None = None) -> list:
        return self._tao.timeline.read(date=date)

    def set_sub_event_sink(self, sink: Callable[..., Any] | None) -> None:
        self._tao.sub_event_sink = sink

    def set_plan_event_sink(self, sink: Any) -> None:
        self._tao.set_plan_event_sink(sink)

    def preload(self) -> None:
        self._tao.preload()

    # ── history restoration ─────────────────────────────────────────────────

    def restore(self, messages: list[dict]) -> None:
        """
        Replay saved Q&A turns into PromptManager.

        `messages` is the raw list stored in the conversation JSON:
          [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]

        Consecutive user/assistant pairs are injected as history turns.
        Silently skips messages with empty content or unexpected ordering.
        """
        self._tao.reset()
        i = 0
        while i < len(messages) - 1:
            u = messages[i]
            a = messages[i + 1]
            if u.get("role") == "user" and a.get("role") == "assistant":
                question = u.get("content", "").strip()
                answer   = a.get("content", "").strip()
                if question and answer:
                    self._tao._manager.add_turn(question, answer)
                i += 2
            else:
                i += 1

    # ── forwarded interface ─────────────────────────────────────────────────

    def stream(self, question: str) -> Generator[TaoEvent, None, None]:
        return self._tao.stream(question)

    def post_process(self, session_id: str = "tao") -> None:
        """Tao 上下文 commit + presence dialogue 记账。"""
        from agent.adapters.soul_dialogue import commit_turn_and_post_process

        commit_turn_and_post_process(
            soul=getattr(self._tao, "_soul", None),
            tao=self._tao,
            session_id=session_id,
        )

    def reset(self, session_id: str = "tao") -> None:
        from agent.soul.life.experience.dialogue import close_dialogue_session

        close_dialogue_session(
            soul=getattr(self._tao, "_soul", None),
            session_id=session_id,
        )
        self._tao.reset()

    def close(self, session_id: str = "tao") -> None:
        from agent.soul.life.experience.dialogue import close_dialogue_session

        close_dialogue_session(
            soul=getattr(self._tao, "_soul", None),
            session_id=session_id,
        )
        self._tao.close()

    def preload_with_recall(self) -> None:
        self._tao.preload_with_recall()

    @property
    def turn_count(self) -> int:
        return self._tao._manager.turn_count
