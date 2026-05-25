from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IncidentKind(str, Enum):
    """Life 侧注入 transition 的事件类型。"""

    landmark_planned = "landmark_planned"
    landmark_filled = "landmark_filled"
    surprise = "surprise"


@dataclass(frozen=True)
class LifeIncident:
    kind: IncidentKind
    session_id: str
    hint: str
    salience: float = 0.4
    trigger: str = ""
    context: str = ""
    emotion_text: str = ""
    emotion_intensity: float = 0.0
    emotion_strength: str = ""
    payload: dict = field(default_factory=dict)

    @staticmethod
    def landmark_planned(
        session_id: str,
        *,
        hint: str,
        context: str = "",
        salience: float = 0.35,
    ) -> LifeIncident:
        return LifeIncident(
            kind=IncidentKind.landmark_planned,
            session_id=session_id,
            hint=hint,
            salience=salience,
            trigger="landmark_planned",
            context=context,
        )

    @staticmethod
    def landmark_filled(
        session_id: str,
        *,
        hint: str,
        salience: float = 0.4,
        trigger: str = "landmark",
        context: str = "",
    ) -> LifeIncident:
        return LifeIncident(
            kind=IncidentKind.landmark_filled,
            session_id=session_id,
            hint=hint,
            salience=salience,
            trigger=trigger,
            context=context,
        )

    @staticmethod
    def surprise(
        session_id: str,
        *,
        hint: str,
        salience: float = 0.5,
        emotion_text: str = "",
        emotion_intensity: float = 0.0,
        emotion_strength: str = "",
    ) -> LifeIncident:
        return LifeIncident(
            kind=IncidentKind.surprise,
            session_id=session_id,
            hint=hint,
            salience=salience,
            trigger="surprise",
            emotion_text=emotion_text,
            emotion_intensity=emotion_intensity,
            emotion_strength=emotion_strength,
        )

    @classmethod
    def from_beat_dict(
        cls,
        kind: IncidentKind,
        beat: dict,
        *,
        session_id: str = "tao",
    ) -> LifeIncident:
        hint = str(beat.get("hint", "")).strip()
        context = str(beat.get("context", "")).strip()
        if kind == IncidentKind.landmark_planned:
            return cls.landmark_planned(
                session_id,
                hint=hint,
                context=context,
                salience=float(beat.get("salience", 0.35)),
            )
        if kind == IncidentKind.landmark_filled:
            return cls.landmark_filled(
                session_id,
                hint=hint,
                salience=float(beat.get("salience", 0.4)),
                trigger=str(beat.get("trigger", "landmark")),
                context=context,
            )
        return cls.surprise(
            session_id,
            hint=hint,
            salience=float(beat.get("salience", 0.5)),
            emotion_text=str(beat.get("emotion_text", "")),
            emotion_intensity=float(beat.get("emotion_intensity", 0.0)),
            emotion_strength=str(beat.get("emotion_strength", "")),
        )
