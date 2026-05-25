from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ...share_desire import ShareDesire


class CaptureKind(str, Enum):
    """演化/边界事件类型（interface 入站）。"""

    user_text = "user_text"
    agent_utterance = "agent_utterance"
    agent_deferred = "agent_deferred"
    scene_enter = "scene_enter"
    proactive_open = "proactive_open"
    proactive_delivered = "proactive_delivered"
    ambiguity_detected = "ambiguity_detected"
    clarify_resolved = "clarify_resolved"
    close = "close"
    wander = "wander"
    landmark = "landmark"
    story_beat = "story_beat"
    surprise = "surprise"


EVOLUTION_KINDS = frozenset(
    {
        CaptureKind.wander,
        CaptureKind.landmark,
        CaptureKind.story_beat,
        CaptureKind.surprise,
    }
)


@dataclass(frozen=True)
class CaptureEvent:
    kind: CaptureKind
    session_id: str
    payload: dict = field(default_factory=dict)

    @staticmethod
    def wander(
        session_id: str,
        *,
        hint: str,
        salience: float,
        source: str = "heartbeat",
        share_desire: ShareDesire | str | None = None,
        emotion_text: str = "",
        emotion_intensity: float = 0.0,
        emotion_strength: str = "",
    ) -> CaptureEvent:
        payload = {
            "hint": hint,
            "salience": salience,
            "source": source,
        }
        if emotion_text:
            payload["emotion_text"] = emotion_text
        if emotion_intensity > 0.0:
            payload["emotion_intensity"] = emotion_intensity
        if emotion_strength:
            payload["emotion_strength"] = emotion_strength
        if share_desire is not None:
            payload["share_desire"] = (
                share_desire.value
                if isinstance(share_desire, ShareDesire)
                else str(share_desire)
            )
        return CaptureEvent(CaptureKind.wander, session_id, payload)

    @staticmethod
    def landmark(
        session_id: str,
        *,
        intention: str,
        context: str = "",
        salience: float = 0.35,
        share_desire: ShareDesire | str | None = ShareDesire.none,
    ) -> CaptureEvent:
        payload = {
            "intention": intention,
            "context": context,
            "salience": salience,
            "source": "landmark",
        }
        if share_desire is not None:
            payload["share_desire"] = (
                share_desire.value
                if isinstance(share_desire, ShareDesire)
                else str(share_desire)
            )
        return CaptureEvent(CaptureKind.landmark, session_id, payload)

    @staticmethod
    def story_beat(
        session_id: str,
        *,
        hint: str,
        salience: float = 0.4,
        trigger: str = "",
        share_desire: ShareDesire | str | None = None,
        emotion_text: str = "",
        emotion_intensity: float = 0.0,
        emotion_strength: str = "",
    ) -> CaptureEvent:
        payload = {
            "hint": hint,
            "salience": salience,
            "source": "story_beat",
            "trigger": trigger,
        }
        if emotion_text:
            payload["emotion_text"] = emotion_text
        if emotion_intensity > 0.0:
            payload["emotion_intensity"] = emotion_intensity
        if emotion_strength:
            payload["emotion_strength"] = emotion_strength
        if share_desire is not None:
            payload["share_desire"] = (
                share_desire.value
                if isinstance(share_desire, ShareDesire)
                else str(share_desire)
            )
        return CaptureEvent(CaptureKind.story_beat, session_id, payload)

    @staticmethod
    def surprise(
        session_id: str,
        *,
        hint: str,
        salience: float = 0.5,
        share_desire: ShareDesire | str | None = ShareDesire.eager,
        emotion_text: str = "",
        emotion_intensity: float = 0.0,
        emotion_strength: str = "",
    ) -> CaptureEvent:
        payload = {
            "hint": hint,
            "salience": salience,
            "source": "surprise",
        }
        if emotion_text:
            payload["emotion_text"] = emotion_text
        if emotion_intensity > 0.0:
            payload["emotion_intensity"] = emotion_intensity
        if emotion_strength:
            payload["emotion_strength"] = emotion_strength
        if share_desire is not None:
            payload["share_desire"] = (
                share_desire.value
                if isinstance(share_desire, ShareDesire)
                else str(share_desire)
            )
        return CaptureEvent(CaptureKind.surprise, session_id, payload)
