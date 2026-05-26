from __future__ import annotations

from typing import Any, Protocol

from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD

from .bundle import SpeakPromptBundle, SpeakTurnMode
from .injected import collect_injected
from .reply_style import SpeakReplyStyle
from .share_queue import ShareQueueComposer, evaluate_share_prompt
from .system import build_system_prompt


class PersonaQueryPort(Protocol):
    """仅请求 persona 稳定层 + self_concept。"""

    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict[str, Any]: ...


class PresenceReadPort(Protocol):
    def snapshot(self, session_id: str): ...


class SpeakPromptComposer:
    """compose 顶层：收集外部注入 → 构造系统提示词 → 组装 bundle。"""

    def __init__(
        self,
        persona: PersonaQueryPort,
        presence: PresenceReadPort,
        *,
        share_threshold: float = PROACTIVE_OPEN_THRESHOLD,
        max_profile_chars: int = 1200,
        max_concept_chars: int = 800,
        max_presence_chars: int = 600,
    ) -> None:
        self._persona = persona
        self._presence = presence
        self._share = ShareQueueComposer(proactive_threshold=share_threshold)
        self._max_profile_chars = max_profile_chars
        self._max_concept_chars = max_concept_chars
        self._max_presence_chars = max_presence_chars

    def compose(
        self,
        session_id: str,
        user_text: str,
        *,
        mode: SpeakTurnMode = "inbound",
        reply_style: SpeakReplyStyle | None = None,
    ) -> SpeakPromptBundle:
        persona_snap = self._persona.get_persona_snapshot(session_id=session_id)
        presence_snap = self._presence.snapshot(session_id)
        share_hint = evaluate_share_prompt(presence_snap)
        drive_eval = self._share.evaluate(presence_snap)
        style = reply_style or SpeakReplyStyle()

        injected = collect_injected(
            persona_snap=persona_snap,
            presence_snap=presence_snap,
            user_text=user_text,
            max_profile_chars=self._max_profile_chars,
            max_concept_chars=self._max_concept_chars,
            max_presence_chars=self._max_presence_chars,
        )
        system = build_system_prompt(
            mode=mode,
            share_hint=share_hint,
            output_format=style.render_prompt(),
        )

        return SpeakPromptBundle(
            session_id=session_id,
            mode=mode,
            injected=injected,
            system=system,
            wants_share=share_hint.wants_share,
            share_summary=share_hint.summary,
            reply_style=style,
            notes=list(drive_eval.notes),
        )
