from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.soul.drive.capture.events import CaptureEvent
from agent.soul.drive.share_desire import ShareDesire
from agent.soul.heartbeat.bridge import MemoryHeartbeatResult

if TYPE_CHECKING:
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
    events: list[CaptureEvent] = field(default_factory=list)
    outbound_count: int = 0


class EvolutionCapture:
    """心跳统一编排：Soul 内部演化 → drive capture。"""

    @staticmethod
    def emit(soul: SoulService, event: CaptureEvent) -> bool:
        if not soul.is_running:
            return False
        result = soul.capture_drive_evolution(event)
        return result.outbound_request is not None

    @staticmethod
    def after_wander(
        soul: SoulService,
        _result: MemoryHeartbeatResult,
        story_beats: list[EvolutionBeat],
        *,
        session_id: str = "tao",
    ) -> EvolutionCaptureReport:
        report = EvolutionCaptureReport()

        for beat in story_beats:
            if not beat.hint.strip():
                continue
            event = CaptureEvent.story_beat(
                session_id,
                hint=beat.hint,
                salience=beat.salience,
                trigger=beat.trigger or beat.source,
                share_desire=beat.share_desire or None,
                emotion_text=beat.emotion_text,
                emotion_intensity=beat.emotion_intensity,
                emotion_strength=beat.emotion_strength,
            )
            report.events.append(event)
            if EvolutionCapture.emit(soul, event):
                report.outbound_count += 1

        return report

    @staticmethod
    def after_landmark_filled(
        soul: SoulService,
        fills: list[EvolutionBeat],
        *,
        session_id: str = "tao",
    ) -> EvolutionCaptureReport:
        report = EvolutionCaptureReport()
        for fill in fills:
            if not fill.hint.strip():
                continue
            event = CaptureEvent.story_beat(
                session_id,
                hint=fill.hint,
                salience=fill.salience,
                trigger=fill.trigger or "landmark",
                share_desire=fill.share_desire or None,
                emotion_text=fill.emotion_text,
                emotion_intensity=fill.emotion_intensity,
                emotion_strength=fill.emotion_strength,
            )
            report.events.append(event)
            if EvolutionCapture.emit(soul, event):
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
        event = CaptureEvent.surprise(
            session_id,
            hint=hint,
            salience=salience,
            share_desire=ShareDesire.eager,
            emotion_text=emotion_text,
            emotion_intensity=emotion_intensity,
            emotion_strength=emotion_strength,
        )
        report.events.append(event)
        if EvolutionCapture.emit(soul, event):
            report.outbound_count += 1
        return report
