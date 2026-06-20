from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from agent.soul.speak.llm.engine import SpeakLLMEngine

from ..identity.collect import collect_stable_portrait
from ..limits import STABLE_HARD_MAX_CHARS
from ..narrative.distill import distill_self_narrative
from ..presence.collect import collect_state_portrait
from .input import PersonaComposeInput
from .records import PersonaDistillRecord
from .refine import refine_self_narrative
from .state import PersonaComposeState
from .store import PersonaComposeStore

if TYPE_CHECKING:
    from agent.soul.speak.io.inbound.compose.store import SpeakStatusStore


class PersonaQueryPort(Protocol):
    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict[str, Any]: ...


class PresenceReadPort(Protocol):
    def snapshot(self, session_id: str): ...


class PersonaComposeService:
    """Persona 域服务：identity + presence → 自叙，支持注入上下文与过往蒸馏记录修订。"""

    def __init__(
        self,
        persona: PersonaQueryPort,
        presence: PresenceReadPort,
        *,
        store: PersonaComposeStore | None = None,
        llm: SpeakLLMEngine | None = None,
        status_store: SpeakStatusStore | None = None,
        max_stable_chars: int = STABLE_HARD_MAX_CHARS,
        max_state_chars: int = 350,
    ) -> None:
        self._persona = persona
        self._presence = presence
        self._store = store or PersonaComposeStore()
        self._llm = llm
        self._status_store = status_store
        self._max_stable_chars = max_stable_chars
        self._max_state_chars = max_state_chars

    def set_llm(self, llm: SpeakLLMEngine | None) -> None:
        self._llm = llm

    def set_status_store(self, status_store: SpeakStatusStore | None) -> None:
        self._status_store = status_store

    def session_record(self, session_id: str):
        return self._store.record(session_id)

    def active(self, session_id: str) -> PersonaComposeState | None:
        return self._store.get(session_id)

    def snapshot(self, session_id: str) -> dict[str, object] | None:
        state = self.active(session_id)
        if state is None:
            return None
        return state.snapshot()

    def version(self, session_id: str) -> int | None:
        state = self.active(session_id)
        if state is None:
            return None
        return state.version

    def clear(self, session_id: str) -> None:
        self._store.clear(session_id)

    def compose_and_set(self, data: PersonaComposeInput) -> PersonaComposeState:
        session_id = data.session_id.strip()
        if not session_id:
            raise ValueError("session_id 不能为空")

        persona_snap = self._persona.get_persona_snapshot(session_id=session_id)
        presence_snap = self._presence.snapshot(session_id)
        stable = collect_stable_portrait(
            persona_snap=persona_snap,
            max_chars=self._max_stable_chars,
        )
        state_text = collect_state_portrait(
            presence_snap=presence_snap,
            max_presence_chars=self._max_state_chars,
            status_store=self._status_store,
        )
        injected = data.injected_context.strip()
        dialogue = data.dialogue_compressed.strip()

        entry = self._store.record(session_id)
        history = data.distill_history
        if not history:
            history = entry.recent_distill_history()

        if (
            not data.force
            and entry.current is not None
            and entry.last_stable == stable
            and entry.last_state == state_text
            and entry.last_injected_context == injected
            and entry.last_dialogue_compressed == dialogue
        ):
            return entry.current

        base_narrative = distill_self_narrative(
            self._llm,
            stable_portrait=stable,
            state_portrait=state_text,
        )
        narrative = refine_self_narrative(
            self._llm,
            base_narrative=base_narrative,
            stable_portrait=stable,
            state_portrait=state_text,
            injected_context=injected,
            distill_history=history,
        )

        version = entry.next_version
        entry.next_version += 1
        composed = PersonaComposeState(
            self_narrative=narrative,
            stable_portrait=stable,
            state_portrait=state_text,
            version=version,
            updated_turn_index=data.turn_index,
            injected_context=injected,
        )
        entry.last_stable = stable
        entry.last_state = state_text
        entry.last_injected_context = injected
        entry.last_dialogue_compressed = dialogue
        entry.current = composed
        entry.append_distill(
            PersonaDistillRecord(
                turn_index=data.turn_index,
                text=narrative,
                kind="narrative",
            )
        )
        return composed
