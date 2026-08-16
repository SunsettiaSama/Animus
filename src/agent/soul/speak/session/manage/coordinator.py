from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..lifecycle.hold.registry import SpeakSessionRegistry
from .enter_greeting import EnterGreetingHandler, EnterGreetingManager
from .initiative import TurnInitiativeManager
from .proactive_window import ProactiveSessionWindowManager
from .silence_break import SilenceBreakHandler, SilenceBreakManager
from .types import EnterGreetingTurnSpec, InitiativeHint, SilenceBreakTurnSpec

@dataclass
class SessionSocialManager:
    """会话弱社交：轮内可选主动 + 长静默打破 + 进入会话话头。"""

    registry: SpeakSessionRegistry
    initiative: TurnInitiativeManager = field(default_factory=TurnInitiativeManager)
    proactive_window: ProactiveSessionWindowManager = field(default_factory=ProactiveSessionWindowManager)
    silence: SilenceBreakManager | None = None
    enter_greeting: EnterGreetingManager | None = None
    # request-driven 的 executable rhythm units 是唯一静默开口调度器。
    # 旧 SilenceBreakManager 仅留给独立组件测试，不在生产会话中调度。
    silence_break_enabled: bool = False
    _dialogue_supplier: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        if self.silence is None:
            self.silence = SilenceBreakManager(registry=self.registry)
        if self.enter_greeting is None:
            self.enter_greeting = EnterGreetingManager(registry=self.registry)

    def set_proactive_timeout_handler(self, handler: Callable[[str], None] | None) -> None:
        self.proactive_window.set_timeout_handler(handler)

    def bind_dialogue_supplier(self, supplier: Callable[[str], str] | None) -> None:
        self._dialogue_supplier = supplier
        self.silence.dialogue_supplier = supplier
        self.enter_greeting.dialogue_supplier = supplier

    def bind_activity(
        self,
        *,
        is_active: Callable[[str], bool] | None = None,
        is_pushing: Callable[[str], bool] | None = None,
    ) -> None:
        self.silence.is_active = is_active
        self.silence.is_pushing = is_pushing
        self.enter_greeting.is_pushing = is_pushing

    def set_silence_break_handler(self, handler: SilenceBreakHandler | None) -> None:
        self.silence.set_break_handler(handler)

    def set_enter_greeting_handler(self, handler: EnterGreetingHandler | None) -> None:
        self.enter_greeting.set_greeting_handler(handler)

    def arm_silence_break(self, spec: SilenceBreakTurnSpec) -> None:
        self.silence.arm_turn(spec)

    def arm_enter_greeting(self, spec: EnterGreetingTurnSpec) -> None:
        self.enter_greeting.arm_turn(spec)

    def clear_session(self, session_id: str) -> None:
        self.initiative.clear_session(session_id)
        self.proactive_window.clear_session(session_id)
        self.silence.clear_session(session_id)
        self.enter_greeting.clear_session(session_id)

    def on_user_message(self, session_id: str) -> None:
        self.proactive_window.touch_user_message(session_id)
        self.silence.on_user_message(session_id)
        self.enter_greeting.on_user_message(session_id)

    def proactive_decay(self, session_id: str) -> float:
        return self.proactive_window.decay(session_id)

    def evaluate_initiative(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        mode: str = "inbound",
    ) -> InitiativeHint | None:
        decay = self.proactive_decay(session_id)
        return self.initiative.evaluate(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
            mode=mode,
            decay=decay if decay > 0 else 1.0,
        )

    def on_turn_complete(
        self,
        session_id: str,
        *,
        mode: str,
        session_state: str,
        answer: str,
    ) -> None:
        if not self.silence_break_enabled:
            return
        if mode != "inbound":
            return
        if session_state != "finish":
            return
        if not answer.strip():
            return
        self.silence.on_agent_turn_complete(session_id)
