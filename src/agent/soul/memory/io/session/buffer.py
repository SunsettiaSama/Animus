from __future__ import annotations

import uuid
from dataclasses import dataclass

from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.memory.domain import EdgeType, MemoryEdge, Valence
from agent.soul.memory.graph.node.create.archive import ExperienceArchiver
from agent.soul.memory.graph.node.create.experience import route_experience_block
from agent.soul.memory.graph.networks.experience_block import ExperienceBlock, ExperienceKind, read_experience_block
from agent.soul.memory.graph.networks.social.node import SocialNeighborhoodNode
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.graph.networks.social.query import SocialQueryEngine
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.ports import GraphEdgeStore, VectorIndexPort

from .integrate import build_session_raw_text, integrate_session_dialogue
from .types import DialogueCompressionBlock, SessionBlockRecord, SessionBufferState


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class SessionMemoryBuffer:
    """会话期临时图连接；闭合时清理临时边并一次性整合入社交记忆。"""

    nodes: GraphNodeStore
    edges: GraphEdgeStore
    traversal: GraphTraversal
    social: SocialMemoryNetwork
    social_query: SocialQueryEngine
    archiver: ExperienceArchiver
    vectors: VectorIndexPort | None
    llm: object
    _sessions: dict[str, SessionBufferState]

    def __init__(
        self,
        *,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        social: SocialMemoryNetwork,
        social_query: SocialQueryEngine,
        archiver: ExperienceArchiver,
        llm: object,
        vectors: VectorIndexPort | None = None,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.traversal = GraphTraversal(edges)
        self.social = social
        self.social_query = social_query
        self.archiver = archiver
        self.vectors = vectors
        self.llm = llm
        self._sessions = {}

    def ingest_session_block(
        self,
        block: DialogueCompressionBlock,
        *,
        interactor_id: str,
    ) -> SessionBlockRecord:
        session_id = block.session_id.strip()
        actor = (interactor_id or block.interactor_id).strip()
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionBufferState(session_id=session_id, interactor_id=actor)
            self._sessions[session_id] = state
        elif actor and not state.interactor_id:
            state.interactor_id = actor

        self.social.ensure_core(state.interactor_id)

        summary = block.summary.strip()
        if not summary:
            summary = block.transcript.strip()[:200] or f"会话块 {block.block_index + 1}"

        valence = _parse_valence(block.valence, block.valence_delta)
        node = SocialNeighborhoodNode(
            id=_new_id(),
            interactor_id=state.interactor_id,
            focus=summary[:60],
            label="session_block",
            content=summary,
            emotion=block.emotion_label.strip(),
            valence=valence,
            base_activation=min(1.0, max(0.35, block.salience + 0.15)),
            meta={
                "session_buffer": True,
                "session_id": session_id,
                "block_index": block.block_index,
                "temporary": True,
            },
        )
        self.nodes.put(node)
        if self.vectors is not None:
            self.vectors.record(node)

        anchor_id, edge_id, edge_weight = self._link_nearest(state.interactor_id, node.id, summary)

        record = SessionBlockRecord(
            block_index=block.block_index,
            node_id=node.id,
            edge_id=edge_id,
            anchor_node_id=anchor_id,
            summary=summary,
            emotion_label=block.emotion_label,
            salience=block.salience,
        )
        state.blocks.append(record)
        return record

    def ingest_fast_experience(
        self,
        unit: ExperienceUnit,
        *,
        interactor_id: str = "",
        agent_persona_narrative: str = "",
    ) -> SessionBlockRecord:
        """快速逻辑：走正式加工链（路由 + 候选 + Agent 选父），但仅写入临时 buffer。"""
        block = read_experience_block(unit)
        session_id = unit.situation.session_id.strip()
        actor = (interactor_id or block.interactor_id).strip()
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionBufferState(session_id=session_id, interactor_id=actor)
            self._sessions[session_id] = state
        elif actor and not state.interactor_id:
            state.interactor_id = actor

        router = self.llm
        routed_block, _reason = route_experience_block(router, block)
        persona = agent_persona_narrative.strip()

        if routed_block.kind == ExperienceKind.anchor:
            archived = self.archiver.archive_anchor(
                routed_block,
                agent_persona_narrative=persona,
            )
            network_label = "social"
        else:
            archived = self.archiver.archive_event(
                routed_block,
                agent_persona_narrative=persona,
            )
            network_label = "event"

        node = archived.node
        node.meta = {
            **node.meta,
            "session_buffer": True,
            "temporary": True,
            "session_id": session_id,
            "life_event_id": block.experience_id,
            "ingest_mode": "dialogue_fast",
        }
        self.nodes.put(node)
        if self.vectors is not None:
            self.vectors.record(node)

        summary = (
            getattr(node, "content", "")
            or getattr(node, "perception", "")
            or getattr(node, "fact", "")
            or routed_block.raw_text[:200]
        ).strip()
        if archived.parent_node_id:
            anchor_id = archived.parent_node_id
            weight = 0.85
        elif routed_block.kind == ExperienceKind.anchor:
            core = self.social.ensure_core(state.interactor_id)
            anchor_id = core.id
            weight = 1.0
        else:
            anchor_id = node.id
            weight = 1.0

        edge = MemoryEdge(
            id=_new_id(),
            from_id=anchor_id,
            to_id=node.id,
            edge_type=EdgeType.related_to,
            weight=weight,
            meta={
                "temporary": True,
                "session_buffer": True,
                "interactor_id": state.interactor_id,
                "semantic_anchor": bool(archived.parent_node_id),
                "ingest_mode": "dialogue_fast",
            },
        )
        self.edges.put(edge)

        block_index = unit.situation.turn_index
        if block_index <= 0:
            block_index = len(state.blocks)

        record = SessionBlockRecord(
            block_index=block_index,
            node_id=node.id,
            edge_id=edge.id,
            anchor_node_id=anchor_id,
            summary=summary[:200],
            emotion_label=routed_block.emotion_label,
            salience=routed_block.salience,
            network=network_label,
        )
        state.blocks.append(record)
        return record

    def close_dialogue_session(
        self,
        session_id: str,
        *,
        interactor_id: str = "",
        final_unit: ExperienceUnit | None = None,
    ) -> list[SocialNeighborhoodNode]:
        session_id = session_id.strip()
        state = self._sessions.pop(session_id, None)
        if state is None:
            if final_unit is not None and interactor_id.strip():
                return self._integrate_without_buffer(
                    interactor_id.strip(),
                    final_unit=final_unit,
                )
            return []

        if interactor_id.strip():
            state.interactor_id = interactor_id.strip()

        self._clear_temporary_edges(state)
        merged = self._integrate_session(state, final_unit=final_unit)
        self._archive_buffer_nodes(state)
        return merged

    def _link_nearest(
        self,
        interactor_id: str,
        block_node_id: str,
        summary: str,
    ) -> tuple[str, str, float]:
        hits = self.social_query.recall(summary, top_k=1, interactor_id=interactor_id)
        if not hits:
            core = self.social.ensure_core(interactor_id)
            anchor_id = core.id
            weight = 1.0
        else:
            anchor_id = hits[0].unit.id
            weight = max(0.5, min(1.0, hits[0].relevance or hits[0].final_score))

        edge = MemoryEdge(
            id=_new_id(),
            from_id=anchor_id,
            to_id=block_node_id,
            edge_type=EdgeType.related_to,
            weight=weight,
            meta={
                "temporary": True,
                "session_buffer": True,
                "interactor_id": interactor_id,
                "semantic_anchor": True,
            },
        )
        self.edges.put(edge)
        return anchor_id, edge.id, weight

    def _clear_temporary_edges(self, state: SessionBufferState) -> None:
        delete = getattr(self.edges, "delete_edge", None)
        if not callable(delete):
            return
        for record in state.blocks:
            if record.edge_id:
                delete(record.edge_id)

    def _archive_buffer_nodes(self, state: SessionBufferState) -> None:
        for record in state.blocks:
            if record.node_id:
                self.nodes.archive(record.node_id)
                if self.vectors is not None:
                    self.vectors.remove(record.node_id)

    def _integrate_session(
        self,
        state: SessionBufferState,
        *,
        final_unit: ExperienceUnit | None,
    ) -> list[SocialNeighborhoodNode]:
        if not state.blocks and final_unit is None:
            return []

        placement = integrate_session_dialogue(
            self.llm,
            state.blocks,
            final_unit=final_unit,
            interactor_id=state.interactor_id,
        )
        raw_text = build_session_raw_text(state.blocks, final_unit=final_unit)
        if not raw_text.strip():
            raw_text = placement.get("subjective_statement", "") or placement.get("focus", "")

        block = ExperienceBlock(
            experience_id=final_unit.id if final_unit is not None else _new_id(),
            source=final_unit.source if final_unit is not None else "interaction",
            kind=ExperienceKind.anchor,
            interactor_id=state.interactor_id,
            raw_text=raw_text,
            emotion_label=str(placement.get("emotion", "")).strip(),
            salience=float(placement.get("base_activation", 0.6) or 0.6),
            valence_delta=0.0,
        )
        archived = self.archiver.archive_anchor(block)
        node = archived.node
        node.focus = str(placement.get("focus", node.focus)).strip()[:60] or node.focus
        node.label = str(placement.get("label", node.label)).strip()[:12] or node.label
        subjective = str(placement.get("subjective_statement", "")).strip()
        if subjective:
            node.content = subjective
        emotion = str(placement.get("emotion", "")).strip()
        if emotion:
            node.emotion = emotion
        valence_raw = str(placement.get("valence", "")).strip().lower()
        if valence_raw in {v.value for v in Valence}:
            node.valence = Valence(valence_raw)
        activation = placement.get("base_activation")
        if activation is not None:
            node.base_activation = min(1.0, max(0.3, float(activation)))

        merged = self.social.merge_neighborhood(
            self.social.ensure_core(state.interactor_id),
            node,
        )
        if archived.parent_node_id and archived.parent_node_id != merged.id:
            self.traversal.link_related_to(archived.parent_node_id, merged.id)
        return [merged]

    def _integrate_without_buffer(
        self,
        interactor_id: str,
        *,
        final_unit: ExperienceUnit,
    ) -> list[SocialNeighborhoodNode]:
        state = SessionBufferState(session_id=final_unit.situation.session_id, interactor_id=interactor_id)
        return self._integrate_session(state, final_unit=final_unit)


def _parse_valence(raw: str, valence_delta: float) -> Valence:
    text = raw.strip().lower()
    if text in {v.value for v in Valence}:
        return Valence(text)
    if valence_delta > 0.15:
        return Valence.positive
    if valence_delta < -0.15:
        return Valence.negative
    return Valence.neutral
