from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .bridge import SpeakDialogueBridge
from .chunk import SpeakFeelingChunk, SpeakSubjectiveChunk, SpeakTurnChunk
from .drive import SpeakDriveBridge, SpeakDriveResult, SpeakDriveSnapshot
from .ports import SpeakDrivePort, SpeakInboundPort, SpeakOutboundPort
from .unit import SpeakAnswer, SpeakExchange, SpeakQuestion

if TYPE_CHECKING:
    from agent.soul.presence import PresenceService


@dataclass
class SpeakIngestResult:
    """用户话语摄入结果。"""

    exchange: SpeakExchange
    notes: list[str] = field(default_factory=list)


@dataclass
class SpeakDeliverResult:
    """对外说话交付结果。"""

    answer: SpeakAnswer
    notes: list[str] = field(default_factory=list)


class SpeakService(SpeakInboundPort, SpeakOutboundPort, SpeakDrivePort):
    """Soul 对话门面：最小问答单元 + 一次穿透 presence / memory 入口。"""

    def __init__(
        self,
        *,
        presence: PresenceService | None = None,
        inbound: SpeakInboundPort | None = None,
        outbound: SpeakOutboundPort | None = None,
        record_turn: Callable[..., None] | None = None,
        dialogue_bridge: SpeakDialogueBridge | None = None,
    ) -> None:
        self._presence = presence
        self._inbound = inbound
        self._outbound = outbound
        self._drive = SpeakDriveBridge(presence)
        on_dialogue = record_turn
        self._dialogue_bridge = dialogue_bridge or SpeakDialogueBridge(
            on_dialogue_turn=on_dialogue,
        )

    @property
    def drive_bridge(self) -> SpeakDriveBridge:
        return self._drive

    @property
    def dialogue_bridge(self) -> SpeakDialogueBridge:
        return self._dialogue_bridge

    def on_user_text(self, session_id: str, text: str) -> SpeakExchange:
        return self.ingest_question(session_id, text).exchange

    def ingest_question(self, session_id: str, text: str) -> SpeakIngestResult:
        exchange = SpeakExchange(
            session_id=session_id,
            question=SpeakQuestion(text=text),
        )
        return SpeakIngestResult(exchange=exchange)

    def deliver(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> SpeakAnswer:
        return self.speak(session_id, text, final=final).answer

    def speak(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> SpeakDeliverResult:
        answer = SpeakAnswer(text=text, final=final)
        return SpeakDeliverResult(answer=answer)

    def record_turn(
        self,
        chunk: SpeakTurnChunk,
    ) -> SpeakIngestResult:
        """一轮对话：speak → presence/experience 连续体验。"""
        exchange = self._dialogue_bridge.record_turn(chunk)
        return SpeakIngestResult(
            exchange=exchange,
            notes=["penetrated: presence/experience"],
        )

    def record_dialogue(
        self,
        session_id: str,
        user_text: str,
        agent_text: str,
        *,
        subjective: SpeakSubjectiveChunk | None = None,
        feeling: SpeakFeelingChunk | None = None,
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
    ) -> SpeakIngestResult:
        chunk = SpeakTurnChunk(
            session_id=session_id,
            user_text=user_text,
            agent_text=agent_text,
            subjective=subjective or SpeakSubjectiveChunk(),
            feeling=feeling or SpeakFeelingChunk(),
            activated_memory_ids=list(activated_memory_ids or []),
            proactive_intent_id=proactive_intent_id,
        )
        return self.record_turn(chunk)

    def drive_snapshot(self, session_id: str) -> SpeakDriveSnapshot:
        return self._drive.snapshot(session_id)

    def evaluate_drive(self, session_id: str) -> SpeakDriveResult:
        return self._drive.evaluate(session_id)

    def tick_intrinsic_drive(self, session_id: str) -> SpeakDriveResult:
        """周期性内驱 tick：读 presence → 判断是否应主动 speak（待实现）。"""
        return self.evaluate_drive(session_id)
