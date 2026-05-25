from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.soul.presence.transition.incident import IncidentKind, LifeIncident
from agent.soul.presence.transition.rumination import RuminationSignal

if TYPE_CHECKING:
    from agent.soul.heartbeat.bridge import MemoryHeartbeatResult
    from agent.soul.service import SoulService


@dataclass
class EvolutionBeat:
    hint: str
    salience: float = 0.4
    trigger: str = ""
    source: str = ""
    share_desire: str = ""
    emotion_text: str = ""
    emotion_intensity: float = 0.0
    emotion_strength: str = ""


@dataclass
class EvolutionCaptureReport:
    events: list[dict] = field(default_factory=list)
    outbound_count: int = 0
    incident_count: int = 0
    rumination_count: int = 0


class EvolutionCapture:
    """心跳统一编排：life 事件 → presence service（FSM 看法 + 可选 speak 冲动）。"""

    @staticmethod
    def _require_running(soul: SoulService) -> bool:
        return soul.is_running

    @staticmethod
    def reflect_incident(
        soul: SoulService,
        kind: IncidentKind,
        beat: dict,
        *,
        session_id: str = "tao",
    ) -> bool:
        if not EvolutionCapture._require_running(soul):
            return False
        incident = LifeIncident.from_beat_dict(kind, beat, session_id=session_id)
        if not incident.hint.strip():
            return False
        result = soul.ingest_presence_incident(incident)
        return result.applied

    @staticmethod
    def reflect_rumination(
        soul: SoulService,
        result: MemoryHeartbeatResult,
        *,
        session_id: str = "tao",
    ) -> bool:
        if not EvolutionCapture._require_running(soul):
            return False
        rumination = RuminationSignal.from_heartbeat_result(result, session_id=session_id)
        if rumination is None:
            return False
        ingest = soul.ingest_presence_rumination(rumination)
        return ingest.applied

    @staticmethod
    def emit_evolution(soul: SoulService, beat: EvolutionBeat, *, session_id: str = "tao") -> bool:
        """演化冲动路径（interface），仍经 service 注入。"""
        if not EvolutionCapture._require_running(soul):
            return False
        if not beat.hint.strip():
            return False
        event = soul.presence_evolution_event(
            session_id=session_id,
            hint=beat.hint,
            salience=beat.salience,
            trigger=beat.trigger or beat.source,
            share_desire=beat.share_desire or None,
            emotion_text=beat.emotion_text,
            emotion_intensity=beat.emotion_intensity,
            emotion_strength=beat.emotion_strength,
        )
        result = soul.capture_presence_evolution(event)
        return result.speak_request is not None

    @staticmethod
    def after_wander(
        soul: SoulService,
        result: MemoryHeartbeatResult,
        story_beats: list[EvolutionBeat],
        *,
        session_id: str = "tao",
    ) -> EvolutionCaptureReport:
        report = EvolutionCaptureReport()
        if RuminationSignal.from_heartbeat_result(result, session_id=session_id) is not None:
            report.rumination_count = 1
        for beat in story_beats:
            if not beat.hint.strip():
                continue
            report.events.append({"hint": beat.hint, "source": "story_beat"})
            if EvolutionCapture.emit_evolution(soul, beat, session_id=session_id):
                report.outbound_count += 1
        return report

    @staticmethod
    def after_landmark_planned(
        soul: SoulService,
        event: dict,
        *,
        session_id: str = "tao",
    ) -> EvolutionCaptureReport:
        report = EvolutionCaptureReport()
        if not event.get("hint"):
            return report
        report.events.append(dict(event))
        if EvolutionCapture.reflect_incident(
            soul,
            IncidentKind.landmark_planned,
            event,
            session_id=session_id,
        ):
            report.incident_count += 1
        beat = EvolutionBeat(
            hint=str(event.get("hint", "")),
            salience=float(event.get("salience", 0.35)),
            trigger="landmark_planned",
            share_desire=str(event.get("share_desire", "")),
        )
        if EvolutionCapture.emit_evolution(soul, beat, session_id=session_id):
            report.outbound_count += 1
        return report

    @staticmethod
    def after_landmark_filled(
        soul: SoulService,
        fills: list[EvolutionBeat] | list[dict],
        *,
        session_id: str = "tao",
    ) -> EvolutionCaptureReport:
        report = EvolutionCaptureReport()
        for raw in fills:
            beat = raw if isinstance(raw, EvolutionBeat) else EvolutionBeat(
                hint=str(raw.get("hint", "")),
                salience=float(raw.get("salience", 0.4)),
                trigger=str(raw.get("trigger", "landmark")),
                source=str(raw.get("source", "")),
                share_desire=str(raw.get("share_desire", "")),
                emotion_text=str(raw.get("emotion_text", "")),
                emotion_intensity=float(raw.get("emotion_intensity", 0.0)),
                emotion_strength=str(raw.get("emotion_strength", "")),
            )
            if not beat.hint.strip():
                continue
            report.events.append({"hint": beat.hint, "source": "landmark_filled"})
            payload = {
                "hint": beat.hint,
                "salience": beat.salience,
                "trigger": beat.trigger,
                "share_desire": beat.share_desire,
                "emotion_text": beat.emotion_text,
                "emotion_intensity": beat.emotion_intensity,
                "emotion_strength": beat.emotion_strength,
            }
            if EvolutionCapture.reflect_incident(
                soul,
                IncidentKind.landmark_filled,
                payload,
                session_id=session_id,
            ):
                report.incident_count += 1
            if EvolutionCapture.emit_evolution(soul, beat, session_id=session_id):
                report.outbound_count += 1
        return report

    @staticmethod
    def after_surprise(
        soul: SoulService,
        *,
        hint: str,
        salience: float = 0.5,
        emotion_text: str = "",
        emotion_intensity: float = 0.0,
        emotion_strength: str = "",
        session_id: str = "tao",
    ) -> EvolutionCaptureReport:
        report = EvolutionCaptureReport()
        if not hint.strip():
            return report
        payload = {
            "hint": hint,
            "salience": salience,
            "emotion_text": emotion_text,
            "emotion_intensity": emotion_intensity,
            "emotion_strength": emotion_strength,
        }
        report.events.append(payload)
        if EvolutionCapture.reflect_incident(
            soul,
            IncidentKind.surprise,
            payload,
            session_id=session_id,
        ):
            report.incident_count += 1
        beat = EvolutionBeat(
            hint=hint,
            salience=salience,
            trigger="surprise",
            share_desire="eager",
            emotion_text=emotion_text,
            emotion_intensity=emotion_intensity,
            emotion_strength=emotion_strength,
        )
        if EvolutionCapture.emit_evolution(soul, beat, session_id=session_id):
            report.outbound_count += 1
        return report
