from __future__ import annotations

from typing import Callable

from agent.soul.memory.domain import ActivatedNode, ActivationCue, ActivationSnapshot, MemoryNetwork
from agent.soul.memory.emergence.spread.engine import spread_activation
from agent.soul.memory.emergence.spread.point_store import PointEmergenceStore
from agent.soul.memory.emergence.spread.snapshot_store import ActivationSnapshotStore, cue_hash
from agent.soul.memory.emergence.spread.associative import (
    merge_hybrid_results,
    perturb_vector,
    sample_associative_intensity,
)
from agent.soul.memory.emergence.types import HotEmergenceResult, PointEmergenceResult
from agent.soul.memory.graph.cluster import ClusterIndex
from agent.soul.memory.graph.query import QueryEngine
from agent.soul.memory.graph.scored import ScoredUnit
from agent.soul.memory.graph.seeds import SeedResolver
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.graph.keywords import extract_keywords
from agent.soul.memory.ports import GraphEdgeStore, VectorIndexPort


class SpreadActivationService:
    """Session spread: cluster seeds + graph propagation; hot store and point+associative query."""

    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        vectors: VectorIndexPort | None,
        query: QueryEngine,
        cluster_index: ClusterIndex,
        *,
        threshold: float = 0.12,
        max_hops: int = 3,
        hop_decay: float = 0.72,
        seed_top_k: int = 8,
        keyword_weight: float = 0.55,
        cluster_core_top_k: int = 4,
        hot_seed_top_k: int = 24,
        hot_max_hops: int = 4,
        point_top_k: int = 5,
        precise_relevance_threshold: float = -1.0,
        associative_sigma: float = 0.15,
        hybrid_w_relevance: float = 0.6,
        hybrid_w_activation: float = 0.4,
        speak_line_max_content: int = 320,
        enqueue: Callable[[Callable[[], None]], None] | None = None,
        query_submit: Callable[[Callable[[], None]], None] | None = None,
        query_rewriter=None,
        beam_walk_enabled: bool = False,
        beam_walk_width: int = 3,
        beam_walk_max_nodes: int = 10,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._traversal = GraphTraversal(edges)
        self._query = query
        self._cluster_index = cluster_index
        self._keyword_weight = keyword_weight
        self._seed_top_k = seed_top_k
        self._cluster_core_top_k = cluster_core_top_k
        self._seeds = SeedResolver(
            nodes,
            vectors,
            keyword_weight=keyword_weight,
            seed_top_k=seed_top_k,
            cluster_index=cluster_index,
            cluster_core_top_k=cluster_core_top_k,
        )
        self._vectors = vectors
        self._threshold = threshold
        self._max_hops = max_hops
        self._hop_decay = hop_decay
        self._hot_seed_top_k = hot_seed_top_k
        self._hot_max_hops = hot_max_hops
        self._point_top_k = point_top_k
        self._precise_relevance_threshold = float(precise_relevance_threshold)
        self._associative_sigma = associative_sigma
        self._hybrid_w_relevance = hybrid_w_relevance
        self._hybrid_w_activation = hybrid_w_activation
        self._speak_line_max_content = max(80, int(speak_line_max_content))
        self._snapshots = ActivationSnapshotStore()
        self._point_store = PointEmergenceStore()
        self._enqueue = enqueue
        self._query_submit = query_submit
        self._point_ready_handlers: list[Callable[[PointEmergenceResult], None]] = []
        # 生产化接线：查询改写（entities→精确种子）+ 语义束搜索（图上流向控制）
        self._query_rewriter = query_rewriter
        self._beam_walk_enabled = bool(beam_walk_enabled)
        self._beam_walk_width = max(1, int(beam_walk_width))
        self._beam_walk_max_nodes = max(1, int(beam_walk_max_nodes))

    def _render_lines(self, scored: list[ScoredUnit]) -> list[str]:
        cap = self._speak_line_max_content
        return [s.render_line(max_content=cap) for s in scored]

    def bind_enqueue(self, enqueue: Callable[[Callable[[], None]], None]) -> None:
        self._enqueue = enqueue
        self._cluster_index.bind_enqueue(enqueue)

    def bind_query_submit(self, query_submit: Callable[[Callable[[], None]], None]) -> None:
        self._query_submit = query_submit

    def on_point_ready(self, handler: Callable[[PointEmergenceResult], None]) -> None:
        self._point_ready_handlers.append(handler)

    def _submit_query(self, fn: Callable[[], None]) -> None:
        if self._query_submit is not None:
            self._query_submit(fn)
            return
        if self._enqueue is not None:
            self._enqueue(fn)
            return
        fn()

    def _notify_point_ready(self, result: PointEmergenceResult) -> None:
        for handler in self._point_ready_handlers:
            handler(result)

    def schedule_cluster_rebuild(self) -> None:
        if self._vectors is None or not hasattr(self._vectors, "iter_entries"):
            return
        entries = self._vectors.iter_entries()
        self._cluster_index.schedule_rebuild(entries)

    def activate_async(self, cue: ActivationCue) -> None:
        self.expand_hot_async(cue)

    def expand_hot_async(self, cue: ActivationCue) -> None:
        if self._enqueue is None:
            self.expand_hot_sync(cue)
            return
        self._enqueue(lambda: self.expand_hot_sync(cue))

    def query_point_async(self, cue: ActivationCue) -> None:
        self._submit_query(lambda: self.query_hybrid_sync(cue))

    def get_snapshot(self, session_id: str) -> ActivationSnapshot | None:
        return self._snapshots.get(session_id)

    def get_point_result(self, session_id: str, turn_index: int) -> PointEmergenceResult | None:
        return self._point_store.get(session_id, turn_index)

    def activate_sync(self, cue: ActivationCue) -> ActivationSnapshot:
        return self._run_spread(cue, seed_top_k=self._seed_top_k, max_hops=self._max_hops)

    def query_spread_sync(self, cue: ActivationCue) -> HotEmergenceResult:
        seed_scores = self._resolve_seeds(cue, seed_top_k=self._hot_seed_top_k)
        activated = self._spread_from_seeds(cue, seed_scores, max_hops=self._hot_max_hops)
        units = self._nodes.get_many([n.unit_id for n in activated])
        scored = [ScoredUnit(u, final_score=n.score) for u, n in zip(units, activated)]
        lines = self._render_lines(scored)
        unit_ids = [s.unit.id for s in scored]
        result = HotEmergenceResult(
            session_id=cue.session_id,
            interactor_id=cue.interactor_id,
            unit_ids=unit_ids,
            lines=lines,
            activated=activated,
            cue_hash=cue_hash(cue.session_id, cue.user_text, cue.agent_text, cue.interactor_id),
        )
        snapshot = ActivationSnapshot(
            session_id=cue.session_id,
            interactor_id=cue.interactor_id,
            nodes=activated,
            cue_hash=result.cue_hash,
        )
        self._snapshots.put(snapshot)
        return result

    def expand_hot_sync(self, cue: ActivationCue) -> HotEmergenceResult:
        return self.query_spread_sync(cue)

    def query_hybrid_sync(
        self,
        cue: ActivationCue,
        *,
        precise_relevance_threshold: float | None = None,
    ) -> PointEmergenceResult:
        return self._run_point_query(
            cue,
            precise_relevance_threshold=precise_relevance_threshold,
        )

    def query_point_sync(self, cue: ActivationCue) -> PointEmergenceResult:
        return self.query_hybrid_sync(cue)

    def rumination_neighbors(
        self,
        node_id: str,
        *,
        max_hops: int = 2,
        top_k: int = 5,
        threshold: float | None = None,
    ) -> list[ScoredUnit]:
        """反刍用轻微语义扩散：以 node 为种子图传播 + 轻量 hybrid 检索。"""
        node = self._nodes.get(node_id)
        if node is None:
            return []

        seed_scores = {node_id: 1.0}
        network_for = {node_id: node.network}
        activated = spread_activation(
            seed_scores,
            self._traversal,
            threshold=threshold if threshold is not None else self._threshold,
            max_hops=max_hops,
            hop_decay=self._hop_decay,
            network_for=network_for,
        )
        ranked: dict[str, ScoredUnit] = {}
        for hit in activated:
            if hit.unit_id == node_id:
                continue
            unit = self._nodes.get(hit.unit_id)
            if unit is None:
                continue
            ranked[hit.unit_id] = ScoredUnit(
                unit,
                relevance=hit.score,
                activation=hit.score,
                final_score=hit.score,
                source="spread",
            )

        text = node.embed_text().strip()
        if text:
            for scored in self._query.hybrid(
                text,
                top_k=top_k,
                w_relevance=self._hybrid_w_relevance,
                w_activation=self._hybrid_w_activation,
            ):
                if scored.unit.id == node_id:
                    continue
                prev = ranked.get(scored.unit.id)
                if prev is None or scored.final_score > prev.final_score:
                    ranked[scored.unit.id] = ScoredUnit(
                        scored.unit,
                        relevance=scored.relevance,
                        activation=scored.activation,
                        final_score=scored.final_score,
                        source="semantic",
                    )

            if self._vectors is not None:
                vector = self._vectors.embed_query(text)
                if vector:
                    intensity = sample_associative_intensity() * 0.55
                    perturbed = perturb_vector(vector, intensity, sigma=self._associative_sigma)
                    if perturbed:
                        for scored in self._query.hybrid_with_vector(
                            perturbed,
                            top_k=max(2, top_k // 2),
                            w_relevance=self._hybrid_w_relevance,
                            w_activation=self._hybrid_w_activation,
                        ):
                            if scored.unit.id == node_id:
                                continue
                            prev = ranked.get(scored.unit.id)
                            blend = scored.final_score * 0.85
                            if prev is None or blend > prev.final_score:
                                ranked[scored.unit.id] = ScoredUnit(
                                    scored.unit,
                                    relevance=scored.relevance,
                                    activation=scored.activation,
                                    final_score=blend,
                                    source="associative",
                                )

        ordered = sorted(ranked.values(), key=lambda s: s.final_score, reverse=True)
        return ordered[:top_k]

    def _merge_wander(self, cue: ActivationCue, result: PointEmergenceResult) -> PointEmergenceResult:
        keywords = extract_keywords(self._cue_text(cue))
        wandered = self._query.wander(n=3, focus_keywords=keywords or None)
        if not wandered:
            return result
        seen = set(result.merged_unit_ids())
        for scored in wandered:
            uid = scored.unit.id
            if uid in seen:
                continue
            seen.add(uid)
            result.associative_lines.append(
                scored.render_line(max_content=self._speak_line_max_content)
            )
            result.associative_unit_ids.append(uid)
        return result

    def _run_point_query(
        self,
        cue: ActivationCue,
        *,
        precise_relevance_threshold: float | None = None,
    ) -> PointEmergenceResult:
        query_text, entities = self._rewritten_cue(cue)
        precise = self._hybrid_precise(
            cue,
            precise_relevance_threshold=precise_relevance_threshold,
            query_text=query_text,
        )
        precise = self._beam_walk_merge(
            cue, precise, query=query_text, entities=entities
        )
        precise_lines = self._render_lines(precise)
        precise_ids = [s.unit.id for s in precise]
        result = PointEmergenceResult(
            session_id=cue.session_id,
            interactor_id=cue.interactor_id,
            turn_index=cue.turn_index,
            precise_lines=precise_lines,
            precise_unit_ids=precise_ids,
            associative_ready=False,
            cue_hash=cue_hash(cue.session_id, cue.user_text, cue.agent_text, cue.interactor_id),
        )
        assoc_result = self._apply_associative(cue, result)
        final = self._merge_wander(cue, assoc_result)
        final.associative_ready = True
        self._point_store.put(final)
        self._push_point_snapshot(final)
        if final.merged_unit_ids():
            self._notify_point_ready(final)
        return final

    def _apply_associative(
        self, cue: ActivationCue, result: PointEmergenceResult
    ) -> PointEmergenceResult:
        query_text, _entities = self._rewritten_cue(cue)
        associative = self._hybrid_associative(cue, query_text=query_text)
        precise_scored = self._nodes.get_many(result.precise_unit_ids)
        precise = [ScoredUnit(u, final_score=1.0) for u in precise_scored]
        precise_ranked, associative_ranked = merge_hybrid_results(precise, associative)
        result.precise_lines = self._render_lines(precise_ranked)
        result.precise_unit_ids = [s.unit.id for s in precise_ranked]
        result.associative_lines = self._render_lines(associative_ranked)
        result.associative_unit_ids = [s.unit.id for s in associative_ranked]
        result.associative_ready = True
        self._point_store.put(result)
        self._push_point_snapshot(result)
        return result

    def _push_point_snapshot(self, result: PointEmergenceResult) -> None:
        unit_ids = result.merged_unit_ids()
        nodes_map = {n.id: n for n in self._nodes.get_many(unit_ids)}
        activated = [
            ActivatedNode(
                unit_id=uid,
                network=nodes_map[uid].network,
                score=1.0,
                hop=0,
            )
            for uid in unit_ids
            if uid in nodes_map
        ]
        snapshot = ActivationSnapshot(
            session_id=result.session_id,
            interactor_id=result.interactor_id,
            nodes=activated,
            cue_hash=result.cue_hash,
        )
        self._snapshots.put(snapshot)

    def _run_spread(
        self,
        cue: ActivationCue,
        *,
        seed_top_k: int,
        max_hops: int,
    ) -> ActivationSnapshot:
        seed_scores = self._resolve_seeds(cue, seed_top_k=seed_top_k)
        activated = self._spread_from_seeds(cue, seed_scores, max_hops=max_hops)
        snapshot = ActivationSnapshot(
            session_id=cue.session_id,
            interactor_id=cue.interactor_id,
            nodes=activated,
            cue_hash=cue_hash(cue.session_id, cue.user_text, cue.agent_text, cue.interactor_id),
        )
        self._snapshots.put(snapshot)
        return snapshot

    def _resolve_seeds(self, cue: ActivationCue, *, seed_top_k: int) -> dict[str, float]:
        text, entities = self._rewritten_cue(cue)
        if not text.strip():
            return {}
        resolver = SeedResolver(
            self._nodes,
            self._vectors,
            keyword_weight=self._keyword_weight,
            seed_top_k=seed_top_k,
            cluster_index=self._cluster_index,
            cluster_core_top_k=self._cluster_core_top_k,
        )
        return resolver.resolve(
            text,
            networks=cue.networks,
            interactor_id=cue.interactor_id,
            entities=entities,
        )

    def _spread_from_seeds(
        self,
        cue: ActivationCue,
        seed_scores: dict[str, float],
        *,
        max_hops: int,
    ) -> list:
        network_for: dict[str, MemoryNetwork] = {}
        for node_id in seed_scores:
            node = self._nodes.get(node_id)
            if node is not None:
                network_for[node_id] = node.network
        return spread_activation(
            seed_scores,
            self._traversal,
            threshold=self._threshold,
            max_hops=max_hops,
            hop_decay=self._hop_decay,
            network_for=network_for,
        )

    def _hybrid_precise(
        self,
        cue: ActivationCue,
        *,
        precise_relevance_threshold: float | None = None,
        query_text: str | None = None,
    ) -> list[ScoredUnit]:
        text = query_text if query_text is not None else self._cue_text(cue)
        if not text.strip():
            return []
        scored = self._query.hybrid(
            text,
            top_k=self._point_top_k,
            w_relevance=self._hybrid_w_relevance,
            w_activation=self._hybrid_w_activation,
            interactor_id=cue.interactor_id,
        )
        threshold = (
            self._precise_relevance_threshold
            if precise_relevance_threshold is None
            else float(precise_relevance_threshold)
        )
        if threshold < 0:
            return scored
        return [s for s in scored if s.relevance >= threshold]

    def _hybrid_associative(
        self, cue: ActivationCue, *, query_text: str | None = None
    ) -> list[ScoredUnit]:
        text = query_text if query_text is not None else self._cue_text(cue)
        if not text.strip() or self._vectors is None:
            return []
        vector = self._vectors.embed_query(text)
        if not vector:
            return []
        intensity = sample_associative_intensity()
        perturbed = perturb_vector(vector, intensity, sigma=self._associative_sigma)
        if not perturbed:
            return []
        return self._query.hybrid_with_vector(
            perturbed,
            top_k=self._point_top_k,
            w_relevance=self._hybrid_w_relevance,
            w_activation=self._hybrid_w_activation,
            interactor_id=cue.interactor_id,
        )

    @staticmethod
    def _cue_text(cue: ActivationCue) -> str:
        return " ".join(part for part in (cue.user_text, cue.agent_text) if part.strip())

    def _rewritten_cue(self, cue: ActivationCue) -> tuple[str, list[str]]:
        """cue 文本 → (改写后 query, entities)；未接 rewriter 时返回原文与空实体。"""
        text = self._cue_text(cue)
        if not text.strip() or self._query_rewriter is None:
            return text, []
        try:
            rr = self._query_rewriter.rewrite(text)
        except Exception:
            return text, []
        return (rr.query or text), list(rr.entities)

    def _beam_walk_merge(
        self,
        cue: ActivationCue,
        precise: list[ScoredUnit],
        *,
        query: str,
        entities: list[str],
    ) -> list[ScoredUnit]:
        """precise 种子 + 实体种子 → 语义束搜索；新触达节点补进 precise 尾部。

        消融结论（kg_walk 臂 +0.078 Hit@k）：改写价值在 entities→精确种子，
        束搜索沿查询语义方向流动，补齐向量路漏掉的图邻域。
        """
        vectors = self._vectors
        if not self._beam_walk_enabled or vectors is None or not hasattr(vectors, "iter_entries"):
            return precise
        try:
            query_vector = vectors.embed_query(query)
        except Exception:
            return precise
        if not query_vector:
            return precise

        seeds: dict[str, float] = {}
        for scored in precise[: self._beam_walk_width]:
            seeds[scored.unit.id] = max(0.1, scored.final_score)
        if entities:
            try:
                seed_scores = self._resolve_seeds_with(cue, query, entities)
            except Exception:
                seed_scores = {}
            for node_id, score in seed_scores.items():
                seeds[node_id] = max(seeds.get(node_id, 0.0), min(score, 0.95))
        if not seeds:
            return precise

        vec_map = {}
        try:
            for entry in vectors.iter_entries():
                if entry.vector:
                    vec_map[entry.node_id] = entry.vector
        except Exception:
            return precise
        if not vec_map:
            return precise

        from infra.retrieval.walk import SemanticBeamWalker

        walker = SemanticBeamWalker(
            lambda node_id: [
                (edge.to_id, edge.weight) for edge in self._edges.out_edges(node_id)
            ],
            lambda node_id: vec_map.get(node_id),
            beam_width=self._beam_walk_width,
            max_nodes=self._beam_walk_max_nodes,
        )
        hits = walker.walk(query_vector, seeds)
        if not hits:
            return precise

        known = {s.unit.id for s in precise}
        extras: list[str] = []
        for hit in hits:
            if hit.node_id not in known and hit.node_id in vec_map:
                extras.append(hit.node_id)
        if not extras:
            return precise
        extra_nodes = {n.id: n for n in self._nodes.get_many(extras) if n is not None}
        budget = max(0, self._point_top_k - len(precise))
        appended = 0
        merged = list(precise)
        for node_id in extras:
            node = extra_nodes.get(node_id)
            if node is None:
                continue
            merged.append(ScoredUnit(node, relevance=0.0, activation=0.0, final_score=0.25, source="beam_walk"))
            appended += 1
            if appended >= budget:
                break
        return merged

    def _resolve_seeds_with(
        self, cue: ActivationCue, text: str, entities: list[str]
    ) -> dict[str, float]:
        if not text.strip():
            return {}
        resolver = SeedResolver(
            self._nodes,
            self._vectors,
            keyword_weight=self._keyword_weight,
            seed_top_k=self._seed_top_k,
            cluster_index=self._cluster_index,
            cluster_core_top_k=self._cluster_core_top_k,
        )
        return resolver.resolve(
            text,
            networks=cue.networks,
            interactor_id=cue.interactor_id,
            entities=entities,
        )
