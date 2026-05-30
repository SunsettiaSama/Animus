from __future__ import annotations

from typing import Protocol

from agent.soul.life.experience.domain.unit import ExperienceUnit

from agent.soul.memory.io.life.mode import MemoryIngestMode

from .request import (
    DialogueCloseAck,
    DialogueCloseInbound,
    ExperienceIngestAck,
    ExperienceIngestInbound,
    ExperienceRetractInbound,
)


class LifeMemoryPort(Protocol):
    """与 life.experience.unit_layer.promote.ports.MemoryIngestPort 对齐。"""

    def ingest_experience(
        self,
        unit: ExperienceUnit,
        *,
        mode: MemoryIngestMode = MemoryIngestMode.formal,
    ) -> None: ...

    def retract_experience(self, life_event_id: str) -> bool: ...

    def close_dialogue_session(
        self,
        session_id: str,
        *,
        interactor_id: str = "",
        final_unit: ExperienceUnit | None = None,
    ) -> None: ...


class LifeMemoryInboundPort(Protocol):
    """Life / Soul 顶层 → Memory IO 入站。"""

    def submit_experience(self, inbound: ExperienceIngestInbound) -> None: ...

    def submit_dialogue_close(self, inbound: DialogueCloseInbound) -> None: ...

    def retract_experience(self, inbound: ExperienceRetractInbound) -> bool: ...


class LifeMemoryChannelPort(Protocol):
    """LifeMemoryChannel 同步处理（worker 线程内执行）。"""

    def ingest_experience(self, inbound: ExperienceIngestInbound) -> ExperienceIngestAck: ...

    def close_dialogue_session(self, inbound: DialogueCloseInbound) -> DialogueCloseAck: ...

    def retract_experience(self, inbound: ExperienceRetractInbound) -> bool: ...
