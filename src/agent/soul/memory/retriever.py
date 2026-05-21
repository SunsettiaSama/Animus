from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agent.soul.memory.embed_text import (
    cluster_key as make_cluster_key,
    cosine_similarity,
    focus_bucket,
    memory_unit_embed_text,
)
from agent.soul.memory.unit import MemoryTier, MemoryUnit, Valence

if TYPE_CHECKING:
    from agent.soul.memory.long_term.manager import LongTermMemoryManager


# ── Backend protocols（解耦向量检索依赖）─────────────────────────────────────

@runtime_checkable
class EmbedderBackend(Protocol):
    """最小嵌入器协议，任何实现 embed() 的对象均满足。"""
    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class VectorBackend(Protocol):
    """最小向量存储协议。

    search() 返回 (unit_id, similarity_score) 列表，相似度 0~1。
    """
    def search(self, vector: list[float], top_k: int) -> list[tuple[str, float]]: ...
    def upsert(self, unit_id: str, vector: list[float]) -> None: ...
    def delete(self, unit_id: str) -> None: ...


# ── 检索结果单元 ─────────────────────────────────────────────────────────────

@dataclass
class ScoredUnit:
    """带评分的记忆单元，作为所有检索模式的统一返回类型。"""

    unit: MemoryUnit
    relevance: float = 1.0
    activation: float = 0.0
    final_score: float = 0.0
    source: str = "memory"

    def render_line(self, max_content: int = 80) -> str:
        line = f"[{self.unit.MEMORY_TYPE}] {self.unit.focus}"
        for attr in ("fact", "reconstructed_fact", "narrative"):
            val = getattr(self.unit, attr, "")
            if val:
                line += f"：{val[:max_content]}"
                break
        return line


@dataclass
class PersonaThemeProfile:
    """Persona 主题簇的质量画像：反复性 × 长时性 × 参与度 × 语义凝聚。"""

    recurrence: int = 0
    span_days: float = 0.0
    cohesion: float = 0.0
    long_term_ratio: float = 0.0
    engagement: float = 0.0
    persona_score: float = 0.0


@dataclass
class PersonaThemeCluster:
    """跨多条记忆的主题聚类，供 Persona buffer 写入 recurring theme 信号。"""

    theme: str
    mass: float
    units: list[ScoredUnit]
    cluster_key: str = ""
    profile: PersonaThemeProfile = field(default_factory=PersonaThemeProfile)

    @property
    def unit_ids(self) -> list[str]:
        return [s.unit.id for s in self.units]

    @property
    def span_days(self) -> float:
        return self.profile.span_days

    @property
    def recurrence(self) -> int:
        return self.profile.recurrence

    @property
    def persona_score(self) -> float:
        return self.profile.persona_score

    def to_buffer_meta(self, tick_id: str = "") -> dict:
        """Persona buffer 元数据（不含记忆正文，含回查锚点）。"""
        return {
            "theme": self.theme,
            "tick_id": tick_id,
            "cluster_key": self.cluster_key,
            "unit_ids": self.unit_ids,
            "mass": round(self.mass, 4),
            "span_days": round(self.profile.span_days, 2),
            "recurrence": self.profile.recurrence,
            "cohesion": round(self.profile.cohesion, 4),
            "persona_score": round(self.profile.persona_score, 4),
            "long_term_ratio": round(self.profile.long_term_ratio, 4),
        }


@dataclass
class PersonaClusterMaterial:
    """月度 drift 回查时返回的聚类材料（含渲染行，不含 buffer 写入）。"""

    theme: str
    cluster_key: str
    mass: float
    profile: PersonaThemeProfile
    units: list[ScoredUnit]

    @property
    def unit_ids(self) -> list[str]:
        return [s.unit.id for s in self.units]

    def to_dict(self) -> dict:
        from agent.soul.memory.codec import scored_to_dict

        return {
            "theme": self.theme,
            "cluster_key": self.cluster_key,
            "unit_ids": self.unit_ids,
            "mass": round(self.mass, 4),
            "span_days": round(self.profile.span_days, 2),
            "recurrence": self.profile.recurrence,
            "cohesion": round(self.profile.cohesion, 4),
            "persona_score": round(self.profile.persona_score, 4),
            "long_term_ratio": round(self.profile.long_term_ratio, 4),
            "units": [scored_to_dict(s) for s in self.units],
            "lines": [s.render_line(max_content=120) for s in self.units],
        }


@dataclass
class _RawPersonaCluster:
    theme: str
    members: list[ScoredUnit]
    cohesion: float = 0.0


# ── MemoryRetriever ───────────────────────────────────────────────────────────

class MemoryRetriever:
    """记忆检索器：单一 MySQL 记忆库 + 可选向量语义检索。"""

    def __init__(
        self,
        store: LongTermMemoryManager,
        recent_half_life_days: float = 3.0,
        half_life_days: float = 30.0,
        embedder: EmbedderBackend | None = None,
        vector_store: VectorBackend | None = None,
    ) -> None:
        self._store = store
        self._recent_hl = recent_half_life_days
        self._hl = half_life_days
        self._embedder = embedder
        self._vector_store = vector_store

    def _activation(self, unit: MemoryUnit, now: datetime) -> float:
        hl = self._recent_hl if unit.tier == MemoryTier.short_term else self._hl
        return unit.activation(now=now, half_life_days=hl)

    def recent(
        self,
        limit: int = 10,
        memory_type: str | None = None,
        **_,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        units = self._store.list_recent(memory_type=memory_type, limit=limit)
        results = [
            ScoredUnit(
                u,
                relevance=1.0,
                activation=self._activation(u, now),
                final_score=self._activation(u, now),
            )
            for u in units
        ]
        results.sort(key=lambda s: s.unit.last_accessed, reverse=True)
        return results[:limit]

    def semantic(self, query: str, top_k: int = 10) -> list[ScoredUnit]:
        if self._embedder is None or self._vector_store is None:
            raise RuntimeError(
                "semantic() 需要 embedder 和 vector_store，"
                "请经 MemoryInfraService 注入。"
            )
        now = datetime.now(timezone.utc)
        vector = self._embedder.embed(query)
        hits = self._vector_store.search(vector, top_k=top_k)
        score_map = {uid: score for uid, score in hits}
        units = self._store.get_many(list(score_map.keys()))
        results: list[ScoredUnit] = []
        for u in units:
            rel = score_map.get(u.id, 0.0)
            act = self._activation(u, now)
            results.append(
                ScoredUnit(u, relevance=rel, activation=act, final_score=rel * act)
            )
        results.sort(key=lambda s: s.final_score, reverse=True)
        return results

    def by_valence(
        self,
        valence: Valence,
        limit: int = 10,
        emotion_hint: str = "",
        **_,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        results = [
            ScoredUnit(
                u,
                relevance=1.0,
                activation=self._activation(u, now),
                final_score=self._activation(u, now),
            )
            for u in self._store.list_recent(valence=valence, limit=limit)
        ]
        if emotion_hint:
            for s in results:
                if emotion_hint in s.unit.emotion:
                    s.final_score = min(1.0, s.final_score * 1.3)
        results.sort(key=lambda s: s.final_score, reverse=True)
        return results[:limit]

    def by_field(
        self,
        memory_type: str | None = None,
        valence: Valence | None = None,
        chapter: str | None = None,
        source_id: str | None = None,
        emotion_contains: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 20,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        units = self._store.query_by_fields(
            memory_type=memory_type,
            valence=valence,
            chapter=chapter,
            source_id=source_id,
            emotion_contains=emotion_contains,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
        )
        results = [
            ScoredUnit(
                u,
                relevance=1.0,
                activation=self._activation(u, now),
                final_score=self._activation(u, now),
            )
            for u in units
        ]
        results.sort(key=lambda s: s.final_score, reverse=True)
        return results

    def hybrid(
        self,
        query: str,
        top_k: int = 5,
        valence: Valence | None = None,
        memory_type: str | None = None,
        w_relevance: float = 0.6,
        w_activation: float = 0.4,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        candidates: list[ScoredUnit] = []

        if self._embedder is not None and self._vector_store is not None:
            vector = self._embedder.embed(query)
            hits = self._vector_store.search(vector, top_k=top_k * 3)
            id_score = {uid: score for uid, score in hits}
            for u in self._store.get_many(list(id_score.keys())):
                act = self._activation(u, now)
                rel = id_score.get(u.id, 0.0)
                candidates.append(ScoredUnit(u, relevance=rel, activation=act))
        else:
            for u in self._store.list_recent(limit=top_k * 2):
                act = self._activation(u, now)
                candidates.append(ScoredUnit(u, relevance=1.0, activation=act))

        if valence is not None:
            candidates = [s for s in candidates if s.unit.valence == valence]
        if memory_type is not None:
            candidates = [s for s in candidates if s.unit.MEMORY_TYPE == memory_type]

        for s in candidates:
            s.final_score = w_relevance * s.relevance + w_activation * s.activation

        candidates.sort(key=lambda s: s.final_score, reverse=True)
        return candidates[:top_k]

    def continuity_for_narrative(
        self,
        query: str,
        *,
        top_k: int = 2,
        candidate_k: int = 12,
        min_relevance: float = 0.30,
        min_final_score: float = 0.12,
        max_score_gap: float = 0.20,
        w_relevance: float = 0.7,
        w_activation: float = 0.3,
    ) -> list[ScoredUnit]:
        q = query.strip()
        if not q:
            return []

        ranked = self.hybrid(
            q,
            top_k=candidate_k,
            w_relevance=w_relevance,
            w_activation=w_activation,
        )
        if not ranked:
            return []

        has_semantic = self._embedder is not None and self._vector_store is not None
        if has_semantic and ranked[0].relevance < min_relevance:
            return []
        if ranked[0].final_score < min_final_score:
            return []

        top = ranked[0].final_score
        floor = top - max_score_gap
        picked: list[ScoredUnit] = []
        for s in ranked:
            if s.final_score < floor:
                break
            if has_semantic and s.relevance < min_relevance:
                continue
            picked.append(s)
            if len(picked) >= top_k:
                break
        return picked

    def wander(
        self,
        n: int = 2,
        emotion_weight: float = 0.5,
        rehearsal_weight: float = 0.3,
        noise: float = 0.2,
        ltm_limit: int = 60,
        focus_keywords: list[str] | None = None,
        keyword_boost: float = 0.28,
        **_,
    ) -> list[ScoredUnit]:
        now = datetime.now(timezone.utc)
        candidates = [
            ScoredUnit(
                u,
                relevance=1.0,
                activation=self._activation(u, now),
            )
            for u in self._store.list_recent(limit=ltm_limit)
        ]
        if not candidates:
            return []

        max_rehearsal = max(s.unit.rehearsal_count for s in candidates) or 1
        saliences: list[float] = []
        for s in candidates:
            u = s.unit
            rehearsal_score = math.log1p(u.rehearsal_count) / math.log1p(max_rehearsal)
            raw = (
                emotion_weight * u.emotion_intensity
                + rehearsal_weight * rehearsal_score
                + noise * random.random()
            )
            if focus_keywords:
                hay = memory_unit_embed_text(u).lower()
                if any(k.strip() and k.strip().lower() in hay for k in focus_keywords):
                    raw += keyword_boost
            saliences.append(max(raw, 1e-6))

        k = min(n, len(candidates))
        chosen_indices = _weighted_sample_without_replacement(saliences, k)
        results: list[ScoredUnit] = []
        for idx in chosen_indices:
            s = candidates[idx]
            s.final_score = saliences[idx]
            results.append(s)
        return results

    def persona_clusters(
        self,
        *,
        ltm_limit: int = 120,
        min_cluster_size: int = 2,
        min_mass: float = 1.8,
        top_k: int = 5,
        similarity_threshold: float = 0.72,
        min_span_days: float = 2.0,
        min_recurrence: int = 2,
        min_cohesion: float = 0.0,
        min_persona_score: float = 0.35,
    ) -> list[PersonaThemeCluster]:
        """Persona 专用：识别跨时间反复出现、语义共事件的 recurring themes。

        评分维度：反复性（跨日共现）、长时性（时间跨度 + long tier）、
        参与度（recall / rehearsal / narrative_ref）、语义凝聚（embedding 簇内相似度）。
        """
        now = datetime.now(timezone.utc)
        candidates = [
            ScoredUnit(
                u,
                relevance=1.0,
                activation=self._activation(u, now),
            )
            for u in self._store.list_recent(limit=ltm_limit)
        ]
        if len(candidates) < min_cluster_size:
            return []

        if self._embedder is not None:
            raw_clusters = self._cluster_by_embedding(
                candidates,
                similarity_threshold=similarity_threshold,
            )
        else:
            raw_clusters = self._cluster_by_focus(candidates)

        scored: list[PersonaThemeCluster] = []
        for raw in raw_clusters:
            members = raw.members
            if len(members) < min_cluster_size:
                continue

            profile = self._build_cluster_profile(members, raw.cohesion, now)
            if profile.recurrence < min_recurrence:
                continue
            if profile.span_days < min_span_days:
                continue
            if self._embedder is not None and profile.cohesion < min_cohesion:
                continue
            if profile.persona_score < min_persona_score:
                continue

            mass = self._cluster_mass(members, profile, now)
            if mass < min_mass:
                continue

            unit_ids = [s.unit.id for s in members]
            scored.append(
                PersonaThemeCluster(
                    theme=raw.theme,
                    mass=mass,
                    units=members,
                    cluster_key=make_cluster_key(raw.theme, unit_ids),
                    profile=profile,
                )
            )

        scored.sort(key=lambda c: (c.mass, c.persona_score), reverse=True)
        return scored[:top_k]

    def fetch_persona_cluster(
        self,
        theme: str,
        *,
        unit_ids: list[str] | None = None,
        cluster_key: str = "",
        top_k: int = 12,
        similarity_threshold: float = 0.60,
        ltm_limit: int = 120,
    ) -> PersonaClusterMaterial:
        """Persona 月度 drift 回查：按主题 + 锚点 unit_ids 拉取共同事件材料。"""
        theme = theme.strip()
        if not theme:
            return PersonaClusterMaterial(
                theme="",
                cluster_key="",
                mass=0.0,
                profile=PersonaThemeProfile(),
                units=[],
            )

        now = datetime.now(timezone.utc)
        seen: set[str] = set()
        candidates: list[ScoredUnit] = []

        anchor_ids = [uid for uid in (unit_ids or []) if uid]
        for u in self._store.get_many(anchor_ids):
            if u.id in seen:
                continue
            seen.add(u.id)
            candidates.append(
                ScoredUnit(
                    u,
                    relevance=1.0,
                    activation=self._activation(u, now),
                )
            )

        if self._embedder is not None and self._vector_store is not None:
            vector = self._embedder.embed(theme)
            hits = self._vector_store.search(vector, top_k=top_k * 3)
            for uid, rel in hits:
                if rel < similarity_threshold or uid in seen:
                    continue
                u = self._store.get(uid)
                if u is None:
                    continue
                seen.add(uid)
                candidates.append(
                    ScoredUnit(
                        u,
                        relevance=rel,
                        activation=self._activation(u, now),
                    )
                )
        else:
            theme_lower = theme.lower()
            bucket = focus_bucket(theme).lower()
            for u in self._store.list_recent(limit=ltm_limit):
                if u.id in seen:
                    continue
                hay = memory_unit_embed_text(u).lower()
                if bucket in hay or theme_lower in hay:
                    seen.add(u.id)
                    candidates.append(
                        ScoredUnit(
                            u,
                            relevance=0.85,
                            activation=self._activation(u, now),
                        )
                    )

        for s in candidates:
            weight = self._persona_unit_weight(s, now)
            s.final_score = weight * (0.45 + 0.55 * s.relevance)

        candidates.sort(key=lambda s: s.final_score, reverse=True)
        picked = candidates[:top_k]

        cohesion = self._cohesion_for_members(picked)
        profile = self._build_cluster_profile(picked, cohesion, now)
        mass = self._cluster_mass(picked, profile, now) if picked else 0.0
        resolved_key = cluster_key or make_cluster_key(theme, [s.unit.id for s in picked])

        return PersonaClusterMaterial(
            theme=theme,
            cluster_key=resolved_key,
            mass=mass,
            profile=profile,
            units=picked,
        )

    def _engagement_score(self, unit: MemoryUnit) -> float:
        raw = (
            0.35 * math.log1p(unit.recall_count)
            + 0.30 * math.log1p(unit.rehearsal_count)
            + 0.35 * math.log1p(unit.narrative_ref_count)
        )
        return min(raw / 2.5, 1.0)

    def _persona_unit_weight(self, scored: ScoredUnit, now: datetime) -> float:
        u = scored.unit
        act = max(scored.activation if scored.activation > 0 else self._activation(u, now), 0.08)
        tier_boost = 1.4 if u.tier == MemoryTier.long else 1.0
        emotional = 1.0 + 0.4 * u.emotion_intensity
        engagement = 1.0 + self._engagement_score(u)
        return act * tier_boost * emotional * engagement

    def _build_cluster_profile(
        self,
        members: list[ScoredUnit],
        cohesion: float,
        now: datetime,
    ) -> PersonaThemeProfile:
        if not members:
            return PersonaThemeProfile()

        dates = [s.unit.created_at for s in members]
        span_days = max((max(dates) - min(dates)).total_seconds() / 86400.0, 0.0)
        recurrence = len({d.date() for d in dates})
        long_term_ratio = sum(
            1 for s in members if s.unit.tier == MemoryTier.long
        ) / len(members)
        engagement = sum(self._engagement_score(s.unit) for s in members) / len(members)

        longevity = min(span_days / 14.0, 1.0) * (0.5 + 0.5 * long_term_ratio)
        recurrence_norm = min(recurrence / 4.0, 1.0)
        persona_score = (
            0.30 * recurrence_norm
            + 0.25 * longevity
            + 0.30 * engagement
            + 0.15 * cohesion
        )
        return PersonaThemeProfile(
            recurrence=recurrence,
            span_days=span_days,
            cohesion=cohesion,
            long_term_ratio=long_term_ratio,
            engagement=engagement,
            persona_score=persona_score,
        )

    def _cluster_mass(
        self,
        members: list[ScoredUnit],
        profile: PersonaThemeProfile,
        now: datetime,
    ) -> float:
        unit_mass = sum(self._persona_unit_weight(s, now) for s in members)
        recurrence_boost = 1.0 + 0.25 * min(profile.recurrence / 3.0, 1.0)
        span_boost = 1.0 + 0.15 * min(profile.span_days / 7.0, 1.0)
        cohesion_boost = 0.75 + 0.25 * profile.cohesion
        return unit_mass * recurrence_boost * span_boost * cohesion_boost

    def _cohesion_for_members(self, members: list[ScoredUnit]) -> float:
        if len(members) <= 1:
            return 1.0 if members else 0.0
        if self._embedder is None:
            buckets = {focus_bucket(s.unit.focus) for s in members}
            return 1.0 if len(buckets) == 1 else 0.55

        vectors = [
            self._embedder.embed(memory_unit_embed_text(s.unit).strip())
            for s in members
        ]
        vectors = [v for v in vectors if v]
        if len(vectors) <= 1:
            return 1.0 if vectors else 0.0

        dim = len(vectors[0])
        centroid = [
            sum(v[d] for v in vectors) / len(vectors)
            for d in range(dim)
        ]
        sims = [cosine_similarity(centroid, v) for v in vectors]
        return sum(sims) / len(sims)

    def _cluster_by_focus(
        self,
        candidates: list[ScoredUnit],
    ) -> list[_RawPersonaCluster]:
        buckets: dict[str, list[ScoredUnit]] = {}
        for s in candidates:
            key = focus_bucket(s.unit.focus)
            buckets.setdefault(key, []).append(s)
        out: list[_RawPersonaCluster] = []
        for key, members in buckets.items():
            cohesion = 1.0 if len(members) == 1 else 0.6
            theme = members[0].unit.focus or key
            out.append(_RawPersonaCluster(theme=theme, members=members, cohesion=cohesion))
        return out

    def _cluster_by_embedding(
        self,
        candidates: list[ScoredUnit],
        *,
        similarity_threshold: float,
    ) -> list[_RawPersonaCluster]:
        embedder = self._embedder
        if embedder is None:
            return self._cluster_by_focus(candidates)

        vectors: list[list[float]] = []
        for s in candidates:
            text = memory_unit_embed_text(s.unit).strip()
            vectors.append(embedder.embed(text) if text else [])

        assigned = [False] * len(candidates)
        clusters: list[_RawPersonaCluster] = []

        for i, seed in enumerate(candidates):
            if assigned[i] or not vectors[i]:
                continue
            member_indices = [i]
            assigned[i] = True
            for j in range(i + 1, len(candidates)):
                if assigned[j] or not vectors[j]:
                    continue
                if cosine_similarity(vectors[i], vectors[j]) >= similarity_threshold:
                    member_indices.append(j)
                    assigned[j] = True

            members = [candidates[idx] for idx in member_indices]
            theme, cohesion = self._summarize_cluster(members, vectors, member_indices)
            clusters.append(_RawPersonaCluster(theme=theme, members=members, cohesion=cohesion))

        for i, s in enumerate(candidates):
            if assigned[i]:
                continue
            key = focus_bucket(s.unit.focus)
            theme = s.unit.focus or key
            clusters.append(
                _RawPersonaCluster(
                    theme=theme,
                    members=[s],
                    cohesion=1.0,
                )
            )
        return clusters

    def _summarize_cluster(
        self,
        members: list[ScoredUnit],
        vectors: list[list[float]],
        indices: list[int],
    ) -> tuple[str, float]:
        if not members:
            return "（未命名）", 0.0
        if len(members) == 1:
            focus = members[0].unit.focus
            return focus or focus_bucket(focus), 1.0

        member_vectors = [vectors[i] for i in indices if vectors[i]]
        if not member_vectors:
            focus = members[0].unit.focus
            return focus or focus_bucket(focus), 0.5

        dim = len(member_vectors[0])
        centroid = [
            sum(v[d] for v in member_vectors) / len(member_vectors)
            for d in range(dim)
        ]
        sims = [cosine_similarity(centroid, v) for v in member_vectors]
        cohesion = sum(sims) / len(sims)
        best_local = sims.index(max(sims))
        medoid = members[best_local]
        theme = medoid.unit.focus or focus_bucket(medoid.unit.focus)
        return theme, cohesion

    def render_block(
        self,
        scored: list[ScoredUnit],
        label: str = "记忆参考",
        max_content: int = 80,
    ) -> str:
        if not scored:
            return ""
        lines = [f"[{label}]"] + [s.render_line(max_content) for s in scored]
        return "\n".join(f"- {l}" if i > 0 else l for i, l in enumerate(lines))


def _weighted_sample_without_replacement(weights: list[float], k: int) -> list[int]:
    if k <= 0 or not weights:
        return []
    keys = [random.random() ** (1.0 / w) for w in weights]
    indexed = sorted(enumerate(keys), key=lambda x: x[1], reverse=True)
    return [i for i, _ in indexed[:k]]
