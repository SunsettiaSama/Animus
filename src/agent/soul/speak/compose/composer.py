from __future__ import annotations

from typing import Any, Protocol

from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD

from .bundle import SpeakPromptBundle, SpeakTurnMode
from .context import SpeakContextDistiller
from .frame import PreparedComposeFrame
from .injected import SpeakInjectedContext, collect_injected
from agent.soul.speak.io.inbound.compose import SpeakStatusStore
from .reply_style import SpeakReplyStyle
from .share import ShareDesireComposer
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
        context_distiller: SpeakContextDistiller | None = None,
        share_composer: ShareDesireComposer | None = None,
        status_store: SpeakStatusStore | None = None,
    ) -> None:
        self._persona = persona
        self._presence = presence
        self._share = share_composer or ShareDesireComposer(
            proactive_threshold=share_threshold,
        )
        self._context = context_distiller
        self._status_store = status_store
        self._max_profile_chars = max_profile_chars
        self._max_concept_chars = max_concept_chars
        self._max_presence_chars = max_presence_chars

    @property
    def share(self) -> ShareDesireComposer:
        return self._share

    def prepare(
        self,
        session_id: str,
        *,
        mode: SpeakTurnMode = "inbound",
        reply_style: SpeakReplyStyle | None = None,
        generation: int = 0,
    ) -> PreparedComposeFrame:
        """后台预组装：persona / status / share → system（不含 user_text）。"""
        persona_snap = self._persona.get_persona_snapshot(session_id=session_id)
        presence_snap = self._presence.snapshot(session_id)
        share_state = self._share.collect(presence_snap)
        drive_eval = self._share.evaluate_drive(presence_snap)
        style = reply_style or SpeakReplyStyle()

        dialogue_compressed = ""
        if self._context is not None:
            dialogue_compressed = self._context.prompt_block(session_id)

        injected = collect_injected(
            persona_snap=persona_snap,
            presence_snap=presence_snap,
            user_text="",
            dialogue_compressed=dialogue_compressed,
            max_profile_chars=self._max_profile_chars,
            max_concept_chars=self._max_concept_chars,
            max_presence_chars=self._max_presence_chars,
            status_store=self._status_store,
        )
        system = build_system_prompt(
            mode=mode,
            share_state=share_state,
            output_format=style.render_prompt(),
        )
        return PreparedComposeFrame(
            session_id=session_id,
            mode=mode,
            generation=generation,
            persona=injected.persona,
            status=injected.status,
            system=system,
            wants_share=share_state.wants_share,
            share_summary=share_state.summary,
            notes=list(drive_eval.notes),
            reply_style=style,
        )

    def finalize(
        self,
        frame: PreparedComposeFrame,
        user_text: str,
    ) -> SpeakPromptBundle:
        """将预组装帧与本轮 user_text 合并为完整 bundle。"""
        injected = SpeakInjectedContext(
            persona=frame.persona,
            status=frame.status,
            user_text=user_text.strip(),
        )
        return SpeakPromptBundle(
            session_id=frame.session_id,
            mode=frame.mode,
            injected=injected,
            system=frame.system,
            wants_share=frame.wants_share,
            share_summary=frame.share_summary,
            reply_style=frame.reply_style,
            notes=list(frame.notes),
            meta={"compose_source": "prefetch"},
        )

    def compose(
        self,
        session_id: str,
        user_text: str,
        *,
        mode: SpeakTurnMode = "inbound",
        reply_style: SpeakReplyStyle | None = None,
    ) -> SpeakPromptBundle:
        frame = self.prepare(session_id, mode=mode, reply_style=reply_style)
        bundle = self.finalize(frame, user_text)
        bundle.meta["compose_source"] = "sync"
        return bundle

    def reveal_share(
        self,
        session_id: str,
        pointer: str,
        *,
        trigger_source: str = "",
    ):
        presence_snap = self._presence.snapshot(session_id)
        return self._share.reveal(
            presence_snap,
            pointer,
            trigger_source=trigger_source,
        )
