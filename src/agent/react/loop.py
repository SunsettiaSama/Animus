from __future__ import annotations

from typing import Generator

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

    def post_process(self) -> None:
        """Delegate to :meth:`TaoLoop.post_process`.

        Runs commit, persona evolution, history update, and static prompt cache
        rebuild.  Call this in a background thread after the ``FinishEvent``
        has been delivered to the client.
        """
        self._tao.post_process()

    def reset(self) -> None:
        self._tao.reset()

    def preload_with_recall(self) -> None:
        self._tao.preload_with_recall()

    @property
    def turn_count(self) -> int:
        return self._tao._manager.turn_count
