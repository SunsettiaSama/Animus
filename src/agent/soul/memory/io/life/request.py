from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.life.experience.domain.unit import ExperienceUnit

from .mode import MemoryIngestMode


@dataclass(frozen=True)
class ExperienceIngestInbound:
    """Life → Memory：体验单元写入记忆图。"""

    unit: ExperienceUnit
    mode: MemoryIngestMode = MemoryIngestMode.formal
    interactor_id: str = ""


@dataclass(frozen=True)
class ExperienceRetractInbound:
    """Life → Memory：按 life_event_id 撤回已写入节点。"""

    life_event_id: str


@dataclass(frozen=True)
class DialogueCloseInbound:
    """Life → Memory：对话会话闭合，整合 SessionMemoryBuffer。"""

    session_id: str
    interactor_id: str = ""
    final_unit: ExperienceUnit | None = None


@dataclass
class ExperienceIngestAck:
    node_ids: list[str] = field(default_factory=list)
    mode: MemoryIngestMode = MemoryIngestMode.formal
    network: str = ""
    route_reason: str = ""
    buffer_record_id: str | None = None


@dataclass
class DialogueCloseAck:
    session_id: str
    interactor_id: str = ""
    merged_node_ids: list[str] = field(default_factory=list)
