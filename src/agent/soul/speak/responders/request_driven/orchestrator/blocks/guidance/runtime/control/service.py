from __future__ import annotations

from agent.soul.speak.llm.engine import SpeakLLMEngine

from .planner import GuidancePlanInput, plan_control_arc
from .render import render_control_arc
from .state import GuidanceControlState, GuidanceSessionRecord, GuidanceTrigger
from .store import GuidanceControlStore


class GuidanceControlService:
    """Guidance 域服务：持有对话控制弧状态，供 orchestrator IO 读写。"""

    def __init__(
        self,
        store: GuidanceControlStore | None = None,
        llm: SpeakLLMEngine | None = None,
    ) -> None:
        self._store = store or GuidanceControlStore()
        self._llm = llm

    def set_llm(self, llm: SpeakLLMEngine | None) -> None:
        self._llm = llm

    def active(self, session_id: str) -> GuidanceControlState | None:
        return self._store.get(session_id)

    def session_record(self, session_id: str) -> GuidanceSessionRecord:
        return self._store.record(session_id)

    def snapshot(self, session_id: str) -> dict[str, object] | None:
        state = self.active(session_id)
        if state is None:
            entry = self._store.record(session_id)
            if not entry.has_control_history():
                return None
            return {
                "version": entry.next_version - 1,
                "brief": entry.last_rhythm_brief(),
                "remaining_turns": 0,
            }
        return state.snapshot()

    def version(self, session_id: str) -> int | None:
        state = self.active(session_id)
        if state is not None:
            return state.version
        entry = self._store.record(session_id)
        if entry.next_version <= 1 and not entry.history:
            return None
        return entry.next_version - 1

    def clear_control_arc(self, session_id: str) -> None:
        self._store.clear(session_id)

    def plan_and_set(self, data: GuidancePlanInput) -> GuidanceControlState:
        entry = self._store.record(data.session_id)
        if entry.current is not None and entry.current.narrative.strip():
            entry.history.append(entry.current.narrative.strip())
            if len(entry.history) > 8:
                entry.history = entry.history[-8:]
        version = entry.next_version
        entry.next_version += 1
        state = plan_control_arc(self._llm, data, version=version)
        entry.current = state
        return state

    def render_active(self, session_id: str) -> str | None:
        state = self.active(session_id)
        if state is None:
            return None
        return render_control_arc(state)

    def on_turn_complete(
        self,
        session_id: str,
        *,
        session_state: str,
    ) -> None:
        if session_state != "finish":
            return
        entry = self._store.record(session_id)
        state = entry.current
        if state is None:
            return
        state.remaining_turns -= 1
        if state.remaining_turns < 1:
            if state.narrative.strip():
                entry.history.append(state.narrative.strip())
            entry.current = None
