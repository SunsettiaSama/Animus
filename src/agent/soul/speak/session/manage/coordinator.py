from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..lifecycle.hold.registry import SpeakSessionRegistry
from .initiative import TurnInitiativeManager
from .silence_break import SilenceBreakHandler, SilenceBreakManager
from .types import InitiativeHint, SilenceBreakTurnSpec

if TYPE_CHECKING:
    from ...compose.bundle import SpeakPromptBundle


@dataclass
class SessionSocialManager:
    """会话弱社交：轮内可选主动 + 长静默打破。

    NOTE: 当前仍以被动应答为主（用户发消息后才 compose）；initiative / silence_break
    只是 prompt 侧的弱提示或补位开口。后续需演进为 agent 引导型主动提问（话题发起、
    节奏主导），而非仅在应答末尾加一句或等静默超时。
    """

    registry: SpeakSessionRegistry
    initiative: TurnInitiativeManager = field(default_factory=TurnInitiativeManager)
    silence: SilenceBreakManager | None = None
    _dialogue_supplier: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        if self.silence is None:
            self.silence = SilenceBreakManager(registry=self.registry)

    def bind_dialogue_supplier(self, supplier: Callable[[str], str] | None) -> None:
        self._dialogue_supplier = supplier
        self.silence.dialogue_supplier = supplier

    def bind_activity(
        self,
        *,
        is_active: Callable[[str], bool] | None = None,
        is_pushing: Callable[[str], bool] | None = None,
    ) -> None:
        self.silence.is_active = is_active
        self.silence.is_pushing = is_pushing

    def set_silence_break_handler(self, handler: SilenceBreakHandler | None) -> None:
        self.silence.set_break_handler(handler)

    def arm_silence_break(self, spec: SilenceBreakTurnSpec) -> None:
        self.silence.arm_turn(spec)

    def clear_session(self, session_id: str) -> None:
        self.initiative.clear_session(session_id)
        self.silence.clear_session(session_id)

    def on_user_message(self, session_id: str) -> None:
        self.silence.on_user_message(session_id)

    def evaluate_initiative(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        mode: str = "inbound",
    ) -> InitiativeHint | None:
        return self.initiative.evaluate(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
            mode=mode,
        )

    def enrich_bundle(
        self,
        bundle: SpeakPromptBundle,
        *,
        session_id: str,
        turn_index: int,
        user_text: str,
        mode: str = "inbound",
    ) -> None:
        armed = self.silence.pop_armed_turn(session_id)
        if armed is not None:
            bundle.social_blocks.append(armed.system_block)
            bundle.notes.append(f"silence_break: armed elapsed={int(armed.elapsed_sec)}s")
            bundle.meta["silence_break"] = True
            bundle.meta["silence_break_user"] = armed.user_text()
            return

        hint = self.evaluate_initiative(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
            mode=mode,
        )
        if hint is not None:
            bundle.social_blocks.append(hint.text)
            bundle.notes.append(hint.note)

    def on_turn_complete(
        self,
        session_id: str,
        *,
        mode: str,
        session_state: str,
        answer: str,
    ) -> None:
        if mode != "inbound":
            return
        if session_state != "finish":
            return
        if not answer.strip():
            return
        self.silence.on_agent_turn_complete(session_id)
