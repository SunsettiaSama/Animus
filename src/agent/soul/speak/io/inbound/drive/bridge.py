from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD

from ....orchestrator.guidance.share import ShareDesireComposer

if TYPE_CHECKING:
    from agent.soul.presence import PresenceService


@dataclass(frozen=True)
class SpeakDriveSnapshot:
    """内驱快照：presence 交互态 + 当下态 FSM 的只读视图。"""

    session_id: str
    impulse_level: float = 0.0
    impulse_reason: str = ""
    impulse_source: str = ""
    share_desire: str = ""
    expectation: str = ""
    presence_narrative: str = ""
    toward_user: float = 0.0
    share_summary: str = ""


@dataclass
class SpeakDriveResult:
    """内驱评估结果：是否应主动对外说话。"""

    snapshot: SpeakDriveSnapshot
    should_speak: bool = False
    speak_reason: str = ""
    notes: list[str] = field(default_factory=list)


class SpeakDriveBridge:
    """内驱入站：presence 冲动/分享意愿 → speak 决策。"""

    def __init__(
        self,
        presence: PresenceService | None = None,
        *,
        share_threshold: float | None = None,
    ) -> None:
        self._presence = presence
        threshold = share_threshold if share_threshold is not None else PROACTIVE_OPEN_THRESHOLD
        self.share_threshold = threshold
        self._share = ShareDesireComposer(proactive_threshold=threshold)

    def snapshot(self, session_id: str) -> SpeakDriveSnapshot:
        if self._presence is None:
            return SpeakDriveSnapshot(session_id=session_id)
        snap = self._presence.snapshot(session_id)
        share_eval = self._share.evaluate_drive(snap)
        interaction = snap.interaction
        return SpeakDriveSnapshot(
            session_id=session_id,
            impulse_level=float(interaction.impulse_level),
            impulse_reason=str(interaction.impulse_reason),
            impulse_source=str(interaction.impulse_source),
            share_desire=str(interaction.share_desire.value),
            expectation=str(snap.expectation.value),
            toward_user=share_eval.toward_user,
            share_summary=share_eval.summary,
        )

    def evaluate(self, session_id: str) -> SpeakDriveResult:
        if self._presence is None:
            snap = self.snapshot(session_id)
            return SpeakDriveResult(snapshot=snap)
        snap = self._presence.snapshot(session_id)
        share_eval = self._share.evaluate_drive(snap)
        drive_snap = self.snapshot(session_id)
        should_speak = share_eval.should_speak or float(snap.interaction.impulse_level) >= 0.35
        speak_reason = share_eval.summary or snap.interaction.impulse_reason
        return SpeakDriveResult(
            snapshot=drive_snap,
            should_speak=should_speak,
            speak_reason=speak_reason,
            notes=list(share_eval.notes),
        )

    def on_speak_request(self, session_id: str, reason: str) -> SpeakDriveResult:
        snap = self.snapshot(session_id)
        return SpeakDriveResult(
            snapshot=snap,
            should_speak=bool(reason.strip()),
            speak_reason=reason,
        )
