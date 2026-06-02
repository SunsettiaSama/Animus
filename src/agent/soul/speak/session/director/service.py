from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from agent.soul.speak.llm.director_engine import DirectorDecision, SpeakDirectorLLMEngine
from langchain_core.messages import HumanMessage, SystemMessage

from .schema import DirectorInput, DirectorSignals

if TYPE_CHECKING:
    from agent.soul.speak.session.queue.hub import SessionQueueHub


@dataclass
class SessionDirectorState:
    last_decision: DirectorDecision | None = None
    last_push_now_at: float = 0.0
    typing_segment_push_used: bool = False
    recent_brew_lines: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        decision = self.last_decision.snapshot() if self.last_decision else {}
        return {
            "last_decision": decision,
            "last_push_now_at": self.last_push_now_at,
            "typing_segment_push_used": self.typing_segment_push_used,
            "recent_brew_lines": list(self.recent_brew_lines),
        }


class SessionDialogueDirector:
    """typing 边沿 / idle 节奏；收拢 share / silence 等主动冲动为 brew。"""

    def __init__(
        self,
        *,
        queues: SessionQueueHub,
        director_llm: SpeakDirectorLLMEngine | None = None,
        push_now_cooldown_sec: float = 8.0,
        brew_queue_max: int = 3,
        deliver_push_now: Callable[[str, str], None] | None = None,
    ) -> None:
        self._queues = queues
        self._llm = director_llm or SpeakDirectorLLMEngine()
        self._push_now_cooldown_sec = max(0.0, push_now_cooldown_sec)
        self._brew_queue_max = max(1, brew_queue_max)
        self._deliver_push_now = deliver_push_now
        self._states: dict[str, SessionDirectorState] = {}

    def clear_session(self, session_id: str) -> None:
        self._states.pop(session_id.strip(), None)

    def state(self, session_id: str) -> SessionDirectorState:
        sid = session_id.strip()
        if sid not in self._states:
            self._states[sid] = SessionDirectorState()
        return self._states[sid]

    def collect_signals(
        self,
        session_id: str,
        *,
        share_state=None,
        deferred_share_count: int = 0,
        silence_armed: bool = False,
    ) -> DirectorSignals:
        wants = False
        summary = ""
        if share_state is not None:
            wants = bool(getattr(share_state, "wants_share", False))
            summary = str(getattr(share_state, "summary", "") or "").strip()
        return DirectorSignals(
            share_wants=wants,
            share_summary=summary,
            share_queue_depth=deferred_share_count,
            silence_armed=silence_armed,
        )

    def on_trigger(
        self,
        session_input: DirectorInput,
        *,
        signals: DirectorSignals,
    ) -> DirectorDecision:
        sid = session_input.session_id.strip()
        state = self.state(sid)
        decision = self._decide(session_input, signals=signals, state=state)
        state.last_decision = decision
        self._apply_decision(sid, session_input, decision, state=state)
        return decision

    def _decide(
        self,
        session_input: DirectorInput,
        *,
        signals: DirectorSignals,
        state: SessionDirectorState,
    ) -> DirectorDecision:
        rule = self._rule_shortcut(session_input, signals=signals)
        if rule is not None:
            return rule
        if not self._llm.available:
            return DirectorDecision(action="hold", reason="director_llm_unconfigured")
        prompt = session_input.prompt_block()
        messages = [
            SystemMessage(content=SpeakDirectorLLMEngine._SYSTEM),
            HumanMessage(content=prompt),
        ]
        return self._llm.decide_messages(messages)

    def _rule_shortcut(
        self,
        session_input: DirectorInput,
        *,
        signals: DirectorSignals,
    ) -> DirectorDecision | None:
        if session_input.trigger == "typing_idle":
            if signals.share_wants and signals.share_summary:
                return DirectorDecision(
                    action="enqueue_brew",
                    lines=[signals.share_summary[:40]],
                    reason="rule_share_idle",
                )
            if signals.share_queue_depth > 0:
                return DirectorDecision(
                    action="enqueue_brew",
                    lines=["（有待分享的话想说）"],
                    reason="rule_deferred_share_idle",
                )
            if signals.silence_armed:
                return DirectorDecision(
                    action="enqueue_brew",
                    lines=["……"],
                    reason="rule_silence_idle",
                )
        return None

    def _apply_decision(
        self,
        session_id: str,
        session_input: DirectorInput,
        decision: DirectorDecision,
        *,
        state: SessionDirectorState,
    ) -> None:
        sid = session_id.strip()
        phase = self._queues.push_phase(sid)
        if decision.action == "push_now":
            if phase == "pushing":
                decision = DirectorDecision(action="hold", reason="pushing_blocks_push_now")
            elif state.typing_segment_push_used:
                decision = DirectorDecision(action="hold", reason="typing_segment_push_cap")
            elif self._push_now_cooldown_sec > 0:
                elapsed = time.monotonic() - state.last_push_now_at
                if state.last_push_now_at > 0 and elapsed < self._push_now_cooldown_sec:
                    decision = DirectorDecision(action="hold", reason="push_now_cooldown")
            if decision.action == "push_now" and decision.lines:
                line = decision.lines[0].strip()
                if line and self._deliver_push_now is not None:
                    self._deliver_push_now(sid, line)
                    state.last_push_now_at = time.monotonic()
                    state.typing_segment_push_used = True
                    state.recent_brew_lines.append(line)
        elif decision.action == "enqueue_brew":
            for line in decision.lines:
                self._queues.enqueue_brew(sid, line)
                state.recent_brew_lines.append(line.strip())
            tail = state.recent_brew_lines[-6:]
            state.recent_brew_lines = tail

    def reset_typing_segment(self, session_id: str) -> None:
        self.state(session_id).typing_segment_push_used = False

    def recent_brew_summary(self, session_id: str) -> str:
        lines = self.state(session_id).recent_brew_lines
        if not lines:
            return ""
        return "最近酝酿/插话：" + "；".join(lines[-3:])
