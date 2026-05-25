from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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


@dataclass
class SpeakDriveResult:
    """内驱评估结果：是否应主动对外说话。"""

    snapshot: SpeakDriveSnapshot
    should_speak: bool = False
    speak_reason: str = ""
    notes: list[str] = field(default_factory=list)


class SpeakDriveBridge:
    """内驱桥：接入 presence 状态机，将冲动/分享意愿转为 speak 层决策（待实现）。"""

    def __init__(self, presence: PresenceService | None = None) -> None:
        self._presence = presence

    def snapshot(self, session_id: str) -> SpeakDriveSnapshot:
        return SpeakDriveSnapshot(session_id=session_id)

    def evaluate(self, session_id: str) -> SpeakDriveResult:
        snap = self.snapshot(session_id)
        return SpeakDriveResult(snapshot=snap)

    def on_speak_request(self, session_id: str, reason: str) -> SpeakDriveResult:
        """interface 门控突破后，speak 层接收主动说话请求的入口（待实现）。"""
        snap = self.snapshot(session_id)
        return SpeakDriveResult(
            snapshot=snap,
            should_speak=False,
            speak_reason=reason,
        )
