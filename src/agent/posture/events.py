"""姿态 FSM 输入事件；由 ``InteractionPosture.dispatch`` 消费，主路径 Soul/Speak 不发送这些事件。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InteractionEventKind(str, Enum):
    """姿态层信号（Agent 输出、外界刺激、场景与生命周期）。"""

    user_text = "user_text"
    agent_utterance = "agent_utterance"
    agent_deferred = "agent_deferred"
    scene_enter = "scene_enter"
    scene_leave = "scene_leave"
    proactive_open = "proactive_open"
    proactive_delivered = "proactive_delivered"
    ambiguity_detected = "ambiguity_detected"
    clarify_resolved = "clarify_resolved"
    turn_closed = "turn_closed"
    close = "close"
    idle_timeout = "idle_timeout"
    continuity_break = "continuity_break"


@dataclass(frozen=True)
class InteractionEvent:
    kind: InteractionEventKind
    session_id: str
    payload: dict = field(default_factory=dict)

    @staticmethod
    def user_text(
        session_id: str,
        text: str = "",
        *,
        ambiguous: bool = False,
        resolves_clarify: bool = False,
    ) -> InteractionEvent:
        return InteractionEvent(
            InteractionEventKind.user_text,
            session_id,
            {
                "text": text,
                "ambiguous": ambiguous,
                "resolves_clarify": resolves_clarify,
            },
        )

    @staticmethod
    def agent_utterance(
        session_id: str,
        *,
        has_question: bool = False,
        final: bool = False,
        notify_only: bool = False,
    ) -> InteractionEvent:
        return InteractionEvent(
            InteractionEventKind.agent_utterance,
            session_id,
            {
                "has_question": has_question,
                "final": final,
                "notify_only": notify_only,
            },
        )

    @staticmethod
    def agent_deferred(session_id: str) -> InteractionEvent:
        return InteractionEvent(
            InteractionEventKind.agent_deferred,
            session_id,
        )

    @staticmethod
    def scene_enter(
        session_id: str,
        *,
        scene_id: str = "",
        scene_kind: str = "",
        title: str = "",
        stakes: str = "",
        admitted: bool = True,
    ) -> InteractionEvent:
        return InteractionEvent(
            InteractionEventKind.scene_enter,
            session_id,
            {
                "scene_id": scene_id,
                "scene_kind": scene_kind,
                "title": title,
                "stakes": stakes,
                "admitted": admitted,
            },
        )

    @staticmethod
    def scene_leave(session_id: str) -> InteractionEvent:
        return InteractionEvent(InteractionEventKind.scene_leave, session_id)

    @staticmethod
    def proactive_open(
        session_id: str,
        *,
        wait_reply: bool = True,
        intent_id: str = "",
        channel: str = "",
    ) -> InteractionEvent:
        return InteractionEvent(
            InteractionEventKind.proactive_open,
            session_id,
            {
                "wait_reply": wait_reply,
                "intent_id": intent_id,
                "channel": channel,
            },
        )

    @staticmethod
    def proactive_delivered(
        session_id: str,
        *,
        intent_id: str = "",
    ) -> InteractionEvent:
        return InteractionEvent(
            InteractionEventKind.proactive_delivered,
            session_id,
            {"intent_id": intent_id},
        )

    @staticmethod
    def ambiguity_detected(session_id: str, reason: str = "") -> InteractionEvent:
        return InteractionEvent(
            InteractionEventKind.ambiguity_detected,
            session_id,
            {"reason": reason},
        )

    @staticmethod
    def clarify_resolved(session_id: str) -> InteractionEvent:
        return InteractionEvent(InteractionEventKind.clarify_resolved, session_id)

    @staticmethod
    def turn_closed(session_id: str) -> InteractionEvent:
        return InteractionEvent(InteractionEventKind.turn_closed, session_id)

    @staticmethod
    def close(session_id: str, reason: str = "") -> InteractionEvent:
        return InteractionEvent(
            InteractionEventKind.close,
            session_id,
            {"reason": reason},
        )

    @staticmethod
    def idle_timeout(session_id: str) -> InteractionEvent:
        return InteractionEvent(InteractionEventKind.idle_timeout, session_id)

    @staticmethod
    def continuity_break(session_id: str) -> InteractionEvent:
        return InteractionEvent(InteractionEventKind.continuity_break, session_id)
