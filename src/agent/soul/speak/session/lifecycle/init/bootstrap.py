from __future__ import annotations

from collections.abc import Callable

from ..hold.registry import SPEAK_SESSION_IDLE_SEC, SpeakSessionRegistry
from ..types import SessionOpenTrigger
from .adapter import SpeakSessionLifecycleAdapter


class SessionBootstrap:
    """会话初始化：registry 接线、generation 跟踪、dialogue 首次启动。"""

    def __init__(
        self,
        *,
        idle_sec: float = SPEAK_SESSION_IDLE_SEC,
        inner_lifecycle=None,
        touch_dialogue: Callable[[str], None] | None = None,
        registry: SpeakSessionRegistry | None = None,
        reset_context: Callable[[str], None] | None = None,
    ) -> None:
        self._reset_context = reset_context or (lambda _sid: None)
        lifecycle = SpeakSessionLifecycleAdapter(
            reset_context=self._reset_context,
            inner=inner_lifecycle,
        )
        self._registry = registry or SpeakSessionRegistry(
            idle_sec=idle_sec,
            lifecycle=lifecycle,
            touch_dialogue=touch_dialogue,
        )
        self._started_generations: dict[str, int] = {}

    @property
    def registry(self) -> SpeakSessionRegistry:
        return self._registry

    @property
    def started_generations(self) -> dict[str, int]:
        return self._started_generations

    def ensure_dialogue_started(
        self,
        session_id: str,
        record,
        *,
        before_generation: int,
        trigger: SessionOpenTrigger = "user_message",
    ) -> tuple[bool, list[str]]:
        notes: list[str] = []
        started = False
        lifecycle = self._registry.lifecycle
        last_started = self._started_generations.get(session_id, 0)
        if lifecycle is not None and record.generation > last_started:
            lifecycle.start_dialogue_session(session_id, trigger=trigger)
            self._started_generations[session_id] = record.generation
            started = True
            if before_generation != record.generation or last_started == 0:
                notes.append(f"session: started dialogue ({trigger})")
        return started, notes

    def on_temporal_rotate(self, session_id: str) -> list[str]:
        self._started_generations.pop(session_id, None)
        return ["session: temporal rotate"]
