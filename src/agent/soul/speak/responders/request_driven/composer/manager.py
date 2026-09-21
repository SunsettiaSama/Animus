from __future__ import annotations

from random import Random

from .config import ComposeManagerConfig
from .domain.compress import TrajectoryCompressor
from .domain.intervention import DirectorMemoryAction, DirectorMemoryIntervention
from .domain.retrieve import MemoryRetrievePolicy, RetrieveHit
from .domain.staging import MemoryStagingBuffer
from .domain.utterance import match_query_from_utterances
from .ports.clock import ClockPort, MonotonicClock
from .ports.memory import BufferEmbedderPort, MemorySearchPort, MemoryUnit, RetrieveMode
from .ports.share_hint import ShareHintPort
from .projectors.director import DirectorContextPort, DirectorContextView
from .projectors.dynamic_layer import DynamicLayerMaterials
from .projectors.role_view import RoleContextView, build_role_context_view


class ComposeManager:
    """动态层材料库：共享 staging / 检索库存。不做注入调度（调度权仅在 Director）。"""

    def __init__(
        self,
        config: ComposeManagerConfig | None = None,
        *,
        memory_search: MemorySearchPort | None = None,
        share_hint: ShareHintPort | None = None,
        clock: ClockPort | None = None,
        rng: Random | None = None,
        embedder: BufferEmbedderPort | None = None,
        query_rewriter=None,
    ) -> None:
        self._config = config or ComposeManagerConfig()
        seed = self._config.rng_seed
        self._rng = rng if rng is not None else Random(seed)
        clock = clock or MonotonicClock()
        self._query_rewriter = query_rewriter
        self._staging = MemoryStagingBuffer(
            memory_search=memory_search,
            share_hint=share_hint,
            clock=clock,
            rng=self._rng,
            max_items=self._config.staging_max_items,
            max_turn_age=self._config.staging_turn_age if hasattr(self._config, "staging_turn_age") else self._config.staging_max_turn_age,
            ttl_sec=self._config.staging_ttl_sec,
            related_ratio=self._config.stage_in_related_ratio,
            stage_in_limit=self._config.stage_in_limit,
        )
        self._role_retrieve = MemoryRetrievePolicy(
            self._staging,
            rng=self._rng,
            embedder=embedder,
            normal_ratio=self._config.retrieve_normal_ratio,
            min_score=self._config.bm25_min_score,
            top_k=self._config.bm25_top_k,
            query_rewriter=query_rewriter,
        )
        director_rng = Random(self._rng.random())
        self._director_retrieve = MemoryRetrievePolicy(
            self._staging,
            rng=director_rng,
            embedder=embedder,
            normal_ratio=self._config.retrieve_normal_ratio,
            min_score=self._config.bm25_min_score,
            top_k=max(1, self._config.director_bm25_top_k),
            query_rewriter=query_rewriter,
        )
        self._trajectory = TrajectoryCompressor(chunk_size=self._config.compress_chunk_size)
        self._director_port = DirectorContextPort(self)
        self._secondary_turns: dict[str, list[tuple[str, str]]] = {}
        self._last_role_hits: dict[str, list[RetrieveHit]] = {}
        self._last_director_hits: dict[str, list[RetrieveHit]] = {}
        self._director_intervene_used: dict[str, int] = {}
        self._embedder = embedder

    @property
    def config(self) -> ComposeManagerConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled)

    @property
    def director_port(self) -> DirectorContextPort:
        return self._director_port

    def set_director_port(self, port: DirectorContextPort) -> None:
        self._director_port = port

    def set_memory_search(self, port: MemorySearchPort) -> None:
        self._staging.set_memory_search(port)

    def set_share_hint(self, port: ShareHintPort) -> None:
        self._staging.set_share_hint(port)

    def set_embedder(self, embedder: BufferEmbedderPort | None) -> None:
        self._embedder = embedder
        self._role_retrieve.set_embedder(embedder)
        self._director_retrieve.set_embedder(embedder)

    def ingest_units(
        self,
        session_id: str,
        units: list[MemoryUnit],
        *,
        kind: str = "related",
    ) -> None:
        """把上游检索/pull 结果压入共享 staging，供 composer 统一淘汰与检索。"""
        self._staging.ingest_units(session_id, units, kind=kind)

    def remove_unit(self, session_id: str, unit_id: str) -> bool:
        return self._staging.remove_unit(session_id, unit_id)

    def buffer_list_units(self, session_id: str) -> list[MemoryUnit]:
        return self._staging.list_units(session_id)

    def buffer_get_unit(self, session_id: str, unit_id: str) -> MemoryUnit | None:
        return self._staging.get_unit(session_id, unit_id)

    def buffer_is_warming(self, session_id: str) -> bool:
        return self._staging.is_warming(session_id)

    def wait_pending_loads(self, session_id: str, *, timeout: float = 2.0) -> bool:
        return self._staging.wait_pending(session_id, timeout=timeout)

    def buffer_search(
        self,
        session_id: str,
        query: str,
        *,
        top_k: int = 3,
        mode: str = "hybrid",
    ) -> list[RetrieveHit]:
        """导演工具 / 外部检索：在 buffer 内按 unit 做 BM25/embedding/hybrid。"""
        sid = session_id.strip()
        retrieve_mode: RetrieveMode = "hybrid"
        key = str(mode or "hybrid").strip().lower()
        if key in ("bm25", "embedding", "hybrid", "random"):
            retrieve_mode = key  # type: ignore[assignment]
        policy = MemoryRetrievePolicy(
            self._staging,
            rng=Random(self._rng.random()),
            embedder=self._embedder,
            normal_ratio=1.0,
            min_score=self._config.bm25_min_score,
            top_k=max(1, int(top_k)),
            query_rewriter=self._query_rewriter,
        )
        return policy.retrieve(
            sid,
            primary_query=match_query_from_utterances(query),
            secondary_query="",
            mode=retrieve_mode,
        )

    def init_session(self, session_id: str, *, query_text: str = "") -> RoleContextView:
        sid = session_id.strip()
        self._trajectory.reset_session(sid)
        self._staging.reset_session(sid)
        self._secondary_turns[sid] = []
        self._last_role_hits.pop(sid, None)
        self._last_director_hits.pop(sid, None)
        self._director_intervene_used[sid] = 0
        # 异步装入：不阻塞主流程
        self._staging.seed_init(sid, query_text=query_text)
        return self.context_for_role(sid, user_text=query_text)

    def on_user_ingress(self, session_id: str, user_text: str) -> None:
        sid = session_id.strip()
        text = user_text.strip()
        self._director_intervene_used[sid] = 0
        self._staging.stage_in(sid, text)

    def on_turn_complete(self, session_id: str, user_text: str, agent_text: str) -> str | None:
        sid = session_id.strip()
        user = user_text.strip()
        agent = agent_text.strip()
        summary = self._trajectory.record_turn(sid, user, agent)
        past = self._secondary_turns.setdefault(sid, [])
        past.append((user, agent))
        if len(past) > self._config.history_query_turns:
            del past[: len(past) - self._config.history_query_turns]
        self._staging.stage_in(sid, f"{user} {agent}".strip())
        if summary and summary.strip():
            block_index = len(self._trajectory.snapshot_texts(sid)[0])
            self._staging.ingest_units(
                sid,
                [
                    MemoryUnit(
                        unit_id=f"traj-{sid}-{block_index}",
                        text=summary.strip(),
                        source="trajectory_compress",
                    )
                ],
                kind="trajectory",
            )
        return summary

    def last_role_hits(self, session_id: str) -> list[RetrieveHit]:
        return list(self._last_role_hits.get(session_id.strip(), []))

    def last_director_hits(self, session_id: str) -> list[RetrieveHit]:
        return list(self._last_director_hits.get(session_id.strip(), []))

    def trajectory_snapshot(
        self,
        session_id: str,
    ) -> tuple[list[str], list[tuple[str, str]]]:
        distilled, working = self._trajectory.snapshot_texts(session_id)
        return list(distilled), [(p.user_text, p.agent_text) for p in working]

    def retrieve_for_role(self, session_id: str, *, user_text: str = "") -> list[RetrieveHit]:
        """角色检索：query 仅用户/过往对话具体输出，不含 system/persona。"""
        sid = session_id.strip()
        secondary = self._secondary_query(sid)
        hits = self._role_retrieve.retrieve(
            sid,
            primary_query=match_query_from_utterances(user_text),
            secondary_query=secondary,
            mode="hybrid",
        )
        self._last_role_hits[sid] = list(hits)
        return hits

    def retrieve_for_director(self, session_id: str, *, user_text: str = "") -> list[RetrieveHit]:
        """导演独立检索：query 仅对话侧具体输出；corpus 为共享 staging（无画像/system）。"""
        sid = session_id.strip()
        distilled, working = self.trajectory_snapshot(sid)
        secondary_parts = list(distilled[-3:])
        secondary_parts.extend(f"{u} {a}".strip() for u, a in working[-2:])
        hits = self._director_retrieve.retrieve(
            sid,
            primary_query=match_query_from_utterances(user_text),
            secondary_query=match_query_from_utterances(*secondary_parts),
            mode="hybrid",
        )
        self._last_director_hits[sid] = list(hits)
        return hits

    def context_for_role(self, session_id: str, *, user_text: str = "") -> RoleContextView:
        """对话轨迹视图；记忆候选只进 materials，不在此自动注入提示词。"""
        sid = session_id.strip()
        distilled, working = self._trajectory.snapshot_texts(sid)
        hits = self.retrieve_for_role(sid, user_text=user_text)
        return build_role_context_view(
            sid,
            distilled=distilled,
            working=working,
            hits=hits,
            meta={
                "primary_query": user_text.strip(),
                "g2_user_only": True,
                "memory_not_auto_injected": True,
                "buffer_warming": self.buffer_is_warming(sid),
            },
        )

    def export_dynamic_materials(
        self,
        session_id: str,
        *,
        user_text: str = "",
        share_texts: list[str] | None = None,
    ) -> DynamicLayerMaterials:
        """导出可调度动态层库存；不决定是否注入。"""
        sid = session_id.strip()
        role_hits = self.retrieve_for_role(sid, user_text=user_text)
        director_hits = self.retrieve_for_director(sid, user_text=user_text)
        shares = tuple(t.strip() for t in (share_texts or []) if t and t.strip())
        return DynamicLayerMaterials(
            session_id=sid,
            memory_ids=tuple(hit.unit.unit_id for hit in role_hits),
            memory_texts=tuple(hit.unit.text for hit in role_hits),
            share_texts=shares,
            director_memory_ids=tuple(hit.unit.unit_id for hit in director_hits),
            director_memory_texts=tuple(hit.unit.text for hit in director_hits),
            meta={
                "provider": "compose_manager.inventory",
                "scheduler": "director_only",
                "buffer_warming": self.buffer_is_warming(sid),
                "buffer_unit_count": len(self.buffer_list_units(sid)),
            },
        )

    def context_for_director(self, session_id: str, *, user_text: str = "") -> DirectorContextView:
        return self._director_port.project(session_id, user_text=user_text)

    def apply_director_memory_intervention(
        self,
        session_id: str,
        intervention: DirectorMemoryIntervention,
    ) -> dict[str, object]:
        """导演干预共享 staging：inject/remove，受 director_memory_intervene_max 约束。"""
        sid = session_id.strip()
        action: DirectorMemoryAction = intervention.action
        if action == "none":
            return {"ok": True, "applied": False, "reason": "none"}
        used = int(self._director_intervene_used.get(sid, 0))
        limit = max(0, int(self._config.director_memory_intervene_max))
        if used >= limit:
            return {
                "ok": False,
                "applied": False,
                "reason": "intervene_limit",
                "used": used,
                "limit": limit,
            }
        if action == "inject":
            text = intervention.text.strip()
            if not text:
                return {"ok": False, "applied": False, "reason": "empty_inject_text"}
            unit_id = intervention.unit_id.strip() or f"dir-inject-{used + 1}-{abs(hash(text)) % 100000}"
            embedding: tuple[float, ...] = ()
            if self._embedder is not None:
                embedding = tuple(float(x) for x in self._embedder.embed(text))
            self._staging.ingest_units(
                sid,
                [
                    MemoryUnit(
                        unit_id=unit_id,
                        text=text,
                        source="director_inject",
                        embedding=embedding,
                    )
                ],
                kind="director_inject",
            )
            self._director_intervene_used[sid] = used + 1
            return {
                "ok": True,
                "applied": True,
                "action": "inject",
                "unit_id": unit_id,
                "used": used + 1,
                "limit": limit,
            }
        if action == "remove":
            unit_id = intervention.unit_id.strip()
            if not unit_id:
                return {"ok": False, "applied": False, "reason": "empty_unit_id"}
            removed = self._staging.remove_unit(sid, unit_id)
            if not removed:
                return {"ok": False, "applied": False, "reason": "unit_not_found", "unit_id": unit_id}
            self._director_intervene_used[sid] = used + 1
            return {
                "ok": True,
                "applied": True,
                "action": "remove",
                "unit_id": unit_id,
                "used": used + 1,
                "limit": limit,
            }
        return {"ok": False, "applied": False, "reason": f"unknown_action:{action}"}

    def reset_session(self, session_id: str) -> None:
        sid = session_id.strip()
        self._trajectory.reset_session(sid)
        self._staging.reset_session(sid)
        self._secondary_turns.pop(sid, None)
        self._last_role_hits.pop(sid, None)
        self._last_director_hits.pop(sid, None)
        self._director_intervene_used.pop(sid, None)

    def _secondary_query(self, session_id: str) -> str:
        return " ".join(
            f"{u} {a}".strip() for u, a in self._secondary_turns.get(session_id, [])
        )
