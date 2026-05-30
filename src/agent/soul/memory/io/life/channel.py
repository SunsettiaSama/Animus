from __future__ import annotations

from agent.soul.memory.graph.node.create.experience import ExperienceGraphIngest
from agent.soul.memory.io.life.mode import MemoryIngestMode
from .deps import LifeIODeps
from .request import (
    DialogueCloseAck,
    DialogueCloseInbound,
    ExperienceIngestAck,
    ExperienceIngestInbound,
    ExperienceRetractInbound,
)


class LifeMemoryChannel:
    """Life ↔ Memory 同步处理层（按 Life 指定的 ingest mode 分发）。"""

    def __init__(self, deps: LifeIODeps) -> None:
        self._deps = deps
        self._formal = ExperienceGraphIngest(
            deps.event,
            deps.social,
            llm=deps.llm,
        )

    def ingest_experience(self, inbound: ExperienceIngestInbound) -> ExperienceIngestAck:
        return self._ingest_formal(inbound)

    def _ingest_formal(self, inbound: ExperienceIngestInbound) -> ExperienceIngestAck:
        persona = self._deps.agent_persona_narrative()
        ingest_result = self._formal.create_nodes(
            inbound.unit,
            agent_persona_narrative=persona,
            route=True,
        )
        node_ids: list[str] = []
        for node in ingest_result.nodes:
            self._deps.rumination.observe_node(node.id)
            node_ids.append(node.id)
        return ExperienceIngestAck(
            node_ids=node_ids,
            mode=MemoryIngestMode.formal,
            route_reason=ingest_result.reason,
            network=ingest_result.network.value if ingest_result.network else "",
        )

    def close_dialogue_session(self, inbound: DialogueCloseInbound) -> DialogueCloseAck:
        """快速内化：不再合并 SessionMemoryBuffer；终局 unit 由 Life 侧已 promote。"""
        _ = inbound
        return DialogueCloseAck(
            session_id=inbound.session_id,
            interactor_id=inbound.interactor_id.strip(),
            merged_node_ids=[],
        )

    def retract_experience(self, inbound: ExperienceRetractInbound) -> bool:
        return self._deps.event.retract_experience(inbound.life_event_id)
