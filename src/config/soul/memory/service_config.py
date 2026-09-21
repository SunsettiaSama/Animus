from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class MemoryServiceConfig:
    """MemoryService 全局配置（单一 MySQL 记忆库 + 可选向量检索）。"""

    recent_half_life_days: float = 3.0
    half_life_days: float = 30.0
    forget_threshold: float = 0.05

    async_ingest: bool = True
    recall_top_k: int = 5

    narrative_continuity_top_k: int = 2
    narrative_continuity_candidate_k: int = 12
    narrative_continuity_min_relevance: float = 0.30
    narrative_continuity_min_final_score: float = 0.12
    narrative_continuity_max_score_gap: float = 0.20

    narrative_threshold: float = 0.65

    persona_cluster_ltm_limit: int = 120
    persona_cluster_min_size: int = 2
    persona_cluster_min_mass: float = 1.8
    persona_cluster_top_k: int = 3
    persona_cluster_similarity: float = 0.72
    persona_cluster_min_span_days: float = 2.0
    persona_cluster_min_recurrence: int = 2
    persona_cluster_min_cohesion: float = 0.0
    persona_cluster_min_persona_score: float = 0.35
    persona_fetch_top_k: int = 12
    persona_fetch_similarity: float = 0.60

    activation_threshold: float = 0.12
    activation_max_hops: int = 3
    activation_hop_decay: float = 0.72
    activation_seed_top_k: int = 8
    activation_keyword_weight: float = 0.55
    activation_snapshot_ttl_sec: float = 300.0

    portrait_probe_min_score: float = 0.12
    portrait_probe_max_score_gap: float = 0.20

    cluster_similarity_threshold: float = 0.72
    cluster_min_size: int = 2
    cluster_core_top_k: int = 4
    cluster_cache_path: str = ".react/soul/memory/cluster_cache.json"

    emergence_query_workers: int = 4
    hot_seed_top_k: int = 24
    hot_max_hops: int = 4
    point_query_top_k: int = 5
    point_precise_relevance_threshold: float = -1.0
    associative_sigma: float = 0.15
    hybrid_w_relevance: float = 0.6
    hybrid_w_activation: float = 0.4
    # 语义束搜索（infra.retrieval 生产化接线）；rewriter 本体开关在
    # config/infra/retrieval.yaml（rewriter.enabled），此处只管图遍历行为
    beam_walk_enabled: bool = True
    beam_walk_width: int = 3
    beam_walk_max_nodes: int = 10
    speak_use_point_query: bool = True
    memory_turn_proximity_max: int = 3
    speak_compose_keyword_wait_ms: int = 200
    speak_compose_memory_budget: int = 5
    speak_compose_memory_wait_ms: int = 100
    # Speak compose 单条记忆行正文上限（render_line max_content）；默认 80 易截断叙事
    speak_memory_line_max_content: int = 320

    # Memory 写入前 sleep 幻觉筛选通道（不影响 SleepService 巩固流程）
    sleep_filter_enabled: bool = True
    sleep_filter_min_salience: float = 0.0
    sleep_filter_reject_unanchored_internal_thought: bool = True

    # 增量式 stack 旁路基座（与 event/social 双网隔离）
    stack_enabled: bool = True
    stack_max_entries: int = 2000
    stack_half_life_days: float = 7.0

    @classmethod
    def from_dict(cls, d: dict) -> MemoryServiceConfig:
        mem = d.get("memory") or d
        svc = d.get("service") or mem.get("service") or {}
        return cls(
            recent_half_life_days=float(
                mem.get("recent_half_life_days", mem.get("short_term", {}).get("half_life_days", 3.0))
            ),
            half_life_days=float(
                mem.get("half_life_days", mem.get("long_term", {}).get("half_life_days", 30.0))
            ),
            forget_threshold=float(
                mem.get("forget_threshold", mem.get("long_term", {}).get("forget_threshold", 0.05))
            ),
            async_ingest=bool(svc.get("async_ingest", True)),
            recall_top_k=int(svc.get("recall_top_k", 5)),
            narrative_continuity_top_k=int(svc.get("narrative_continuity_top_k", 2)),
            narrative_continuity_candidate_k=int(
                svc.get("narrative_continuity_candidate_k", 12)
            ),
            narrative_continuity_min_relevance=float(
                svc.get("narrative_continuity_min_relevance", 0.30)
            ),
            narrative_continuity_min_final_score=float(
                svc.get("narrative_continuity_min_final_score", 0.12)
            ),
            narrative_continuity_max_score_gap=float(
                svc.get("narrative_continuity_max_score_gap", 0.20)
            ),
            narrative_threshold=float(svc.get("narrative_threshold", 0.65)),
            persona_cluster_ltm_limit=int(svc.get("persona_cluster_ltm_limit", 120)),
            persona_cluster_min_size=int(svc.get("persona_cluster_min_size", 2)),
            persona_cluster_min_mass=float(svc.get("persona_cluster_min_mass", 1.8)),
            persona_cluster_top_k=int(svc.get("persona_cluster_top_k", 3)),
            persona_cluster_similarity=float(svc.get("persona_cluster_similarity", 0.72)),
            persona_cluster_min_span_days=float(svc.get("persona_cluster_min_span_days", 2.0)),
            persona_cluster_min_recurrence=int(svc.get("persona_cluster_min_recurrence", 2)),
            persona_cluster_min_cohesion=float(svc.get("persona_cluster_min_cohesion", 0.0)),
            persona_cluster_min_persona_score=float(
                svc.get("persona_cluster_min_persona_score", 0.35)
            ),
            persona_fetch_top_k=int(svc.get("persona_fetch_top_k", 12)),
            persona_fetch_similarity=float(svc.get("persona_fetch_similarity", 0.60)),
            activation_threshold=float(svc.get("activation_threshold", 0.12)),
            activation_max_hops=int(svc.get("activation_max_hops", 3)),
            activation_hop_decay=float(svc.get("activation_hop_decay", 0.72)),
            activation_seed_top_k=int(svc.get("activation_seed_top_k", 8)),
            activation_keyword_weight=float(svc.get("activation_keyword_weight", 0.55)),
            activation_snapshot_ttl_sec=float(svc.get("activation_snapshot_ttl_sec", 300.0)),
            portrait_probe_min_score=float(svc.get("portrait_probe_min_score", 0.12)),
            portrait_probe_max_score_gap=float(svc.get("portrait_probe_max_score_gap", 0.20)),
            cluster_similarity_threshold=float(svc.get("cluster_similarity_threshold", 0.72)),
            cluster_min_size=int(svc.get("cluster_min_size", 2)),
            cluster_core_top_k=int(svc.get("cluster_core_top_k", 4)),
            cluster_cache_path=str(svc.get("cluster_cache_path", ".react/soul/memory/cluster_cache.json")),
            emergence_query_workers=int(svc.get("emergence_query_workers", 4)),
            hot_seed_top_k=int(svc.get("hot_seed_top_k", 24)),
            hot_max_hops=int(svc.get("hot_max_hops", 4)),
            point_query_top_k=int(svc.get("point_query_top_k", 5)),
            point_precise_relevance_threshold=float(
                svc.get("point_precise_relevance_threshold", -1.0)
            ),
            associative_sigma=float(svc.get("associative_sigma", 0.15)),
            hybrid_w_relevance=float(svc.get("hybrid_w_relevance", 0.6)),
            hybrid_w_activation=float(svc.get("hybrid_w_activation", 0.4)),
            beam_walk_enabled=bool(svc.get("beam_walk_enabled", True)),
            beam_walk_width=int(svc.get("beam_walk_width", 3)),
            beam_walk_max_nodes=int(svc.get("beam_walk_max_nodes", 10)),
            speak_use_point_query=bool(svc.get("speak_use_point_query", True)),
            memory_turn_proximity_max=int(svc.get("memory_turn_proximity_max", 3)),
            speak_compose_keyword_wait_ms=int(svc.get("speak_compose_keyword_wait_ms", 200)),
            speak_compose_memory_budget=int(svc.get("speak_compose_memory_budget", 5)),
            speak_compose_memory_wait_ms=int(svc.get("speak_compose_memory_wait_ms", 100)),
            speak_memory_line_max_content=int(
                svc.get("speak_memory_line_max_content", 320)
            ),
            sleep_filter_enabled=bool(svc.get("sleep_filter_enabled", True)),
            sleep_filter_min_salience=float(svc.get("sleep_filter_min_salience", 0.0)),
            sleep_filter_reject_unanchored_internal_thought=bool(
                svc.get("sleep_filter_reject_unanchored_internal_thought", True)
            ),
            stack_enabled=bool(svc.get("stack_enabled", True)),
            stack_max_entries=int(svc.get("stack_max_entries", 2000)),
            stack_half_life_days=float(svc.get("stack_half_life_days", 7.0)),
        )

    @classmethod
    def from_yaml(cls, path: str) -> MemoryServiceConfig:
        import yaml

        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def load_default(cls) -> MemoryServiceConfig:
        here = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.normpath(os.path.join(here, "..", "..", "..", ".."))
        default_path = os.path.join(project_root, "config", "soul", "memory", "service.yaml")
        return cls.from_yaml(default_path)

    def to_dict(self) -> dict:
        return {
            "short_term": {"half_life_days": self.recent_half_life_days},
            "long_term": {
                "half_life_days": self.half_life_days,
                "forget_threshold": self.forget_threshold,
            },
            "service": {
                "async_ingest": self.async_ingest,
                "recall_top_k": self.recall_top_k,
                "narrative_continuity_top_k": self.narrative_continuity_top_k,
                "narrative_continuity_candidate_k": self.narrative_continuity_candidate_k,
                "narrative_continuity_min_relevance": self.narrative_continuity_min_relevance,
                "narrative_continuity_min_final_score": self.narrative_continuity_min_final_score,
                "narrative_continuity_max_score_gap": self.narrative_continuity_max_score_gap,
                "narrative_threshold": self.narrative_threshold,
                "persona_cluster_ltm_limit": self.persona_cluster_ltm_limit,
                "persona_cluster_min_size": self.persona_cluster_min_size,
                "persona_cluster_min_mass": self.persona_cluster_min_mass,
                "persona_cluster_top_k": self.persona_cluster_top_k,
                "persona_cluster_similarity": self.persona_cluster_similarity,
                "persona_cluster_min_span_days": self.persona_cluster_min_span_days,
                "persona_cluster_min_recurrence": self.persona_cluster_min_recurrence,
                "persona_cluster_min_cohesion": self.persona_cluster_min_cohesion,
                "persona_cluster_min_persona_score": self.persona_cluster_min_persona_score,
                "persona_fetch_top_k": self.persona_fetch_top_k,
                "persona_fetch_similarity": self.persona_fetch_similarity,
                "activation_threshold": self.activation_threshold,
                "activation_max_hops": self.activation_max_hops,
                "activation_hop_decay": self.activation_hop_decay,
                "activation_seed_top_k": self.activation_seed_top_k,
                "activation_keyword_weight": self.activation_keyword_weight,
                "activation_snapshot_ttl_sec": self.activation_snapshot_ttl_sec,
                "portrait_probe_min_score": self.portrait_probe_min_score,
                "portrait_probe_max_score_gap": self.portrait_probe_max_score_gap,
                "cluster_similarity_threshold": self.cluster_similarity_threshold,
                "cluster_min_size": self.cluster_min_size,
                "cluster_core_top_k": self.cluster_core_top_k,
                "cluster_cache_path": self.cluster_cache_path,
                "emergence_query_workers": self.emergence_query_workers,
                "hot_seed_top_k": self.hot_seed_top_k,
                "hot_max_hops": self.hot_max_hops,
                "point_query_top_k": self.point_query_top_k,
                "point_precise_relevance_threshold": self.point_precise_relevance_threshold,
                "associative_sigma": self.associative_sigma,
                "hybrid_w_relevance": self.hybrid_w_relevance,
                "hybrid_w_activation": self.hybrid_w_activation,
                "beam_walk_enabled": self.beam_walk_enabled,
                "beam_walk_width": self.beam_walk_width,
                "beam_walk_max_nodes": self.beam_walk_max_nodes,
                "speak_use_point_query": self.speak_use_point_query,
                "memory_turn_proximity_max": self.memory_turn_proximity_max,
                "speak_compose_keyword_wait_ms": self.speak_compose_keyword_wait_ms,
                "speak_compose_memory_budget": self.speak_compose_memory_budget,
                "speak_compose_memory_wait_ms": self.speak_compose_memory_wait_ms,
                "speak_memory_line_max_content": self.speak_memory_line_max_content,
                "sleep_filter_enabled": self.sleep_filter_enabled,
                "sleep_filter_min_salience": self.sleep_filter_min_salience,
                "sleep_filter_reject_unanchored_internal_thought": (
                    self.sleep_filter_reject_unanchored_internal_thought
                ),
                "stack_enabled": self.stack_enabled,
                "stack_max_entries": self.stack_max_entries,
                "stack_half_life_days": self.stack_half_life_days,
            },
        }

    def save_yaml(self, path: str) -> None:
        import yaml

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                self.to_dict(),
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
