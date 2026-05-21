from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from agent.soul.memory.embed_text import (
    cosine_similarity,
    focus_bucket,
    memory_unit_embed_text,
)
from agent.soul.memory.unit import MemoryUnit


@runtime_checkable
class EmbedderBackend(Protocol):
    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class DriftClusterConfig:
    """漂移聚类默认参数（用户无感知，内部固定）。"""

    similarity_threshold: float = 0.68
    min_cluster_size: int = 1
    max_clusters: int = 6
    max_lines_per_cluster: int = 8
    line_max_chars: int = 120


@dataclass
class DriftUnitCluster:
    """一次漂移蒸馏的 batch 单位：语义相近的一组 memory unit。"""

    theme: str
    units: list[MemoryUnit] = field(default_factory=list)
    cohesion: float = 0.0

    def lines(self, *, max_lines: int = 8, max_content: int = 120) -> list[str]:
        out: list[str] = []
        for unit in self.units[:max_lines]:
            line = _render_unit_line(unit, max_content=max_content)
            if line.strip():
                out.append(line)
        return out


def _render_unit_line(unit: MemoryUnit, *, max_content: int) -> str:
    line = f"[{unit.MEMORY_TYPE}] {unit.focus}"
    for attr in ("fact", "reconstructed_fact", "narrative", "perception"):
        val = getattr(unit, attr, "")
        if val:
            line += f"：{str(val)[:max_content]}"
            break
    return line


def cluster_memory_units(
    units: list[MemoryUnit],
    embedder: EmbedderBackend | None,
    *,
    cfg: DriftClusterConfig | None = None,
) -> list[DriftUnitCluster]:
    """对 raw memory units 做语义聚类，供分簇蒸馏使用。"""
    c = cfg or DriftClusterConfig()
    if not units:
        return []

    if embedder is not None:
        clusters = _cluster_by_embedding(units, embedder, c.similarity_threshold)
    else:
        clusters = _cluster_by_focus(units)

    if c.min_cluster_size > 1:
        clusters = [cl for cl in clusters if len(cl.units) >= c.min_cluster_size]

    clusters.sort(key=lambda cl: len(cl.units), reverse=True)
    if c.max_clusters > 0 and len(clusters) > c.max_clusters:
        clusters = clusters[: c.max_clusters]

    for cl in clusters:
        cap = c.max_lines_per_cluster
        if cap > 0 and len(cl.units) > cap:
            cl.units = cl.units[:cap]
    return clusters


def _cluster_by_focus(units: list[MemoryUnit]) -> list[DriftUnitCluster]:
    buckets: dict[str, list[MemoryUnit]] = {}
    for unit in units:
        key = focus_bucket(unit.focus)
        buckets.setdefault(key, []).append(unit)
    out: list[DriftUnitCluster] = []
    for key, members in buckets.items():
        theme = members[0].focus or key
        cohesion = 1.0 if len(members) == 1 else 0.6
        out.append(DriftUnitCluster(theme=theme, units=list(members), cohesion=cohesion))
    return out


def _cluster_by_embedding(
    units: list[MemoryUnit],
    embedder: EmbedderBackend,
    similarity_threshold: float,
) -> list[DriftUnitCluster]:
    vectors: list[list[float]] = []
    for unit in units:
        text = memory_unit_embed_text(unit).strip()
        vectors.append(embedder.embed(text) if text else [])

    assigned = [False] * len(units)
    clusters: list[DriftUnitCluster] = []

    for i in range(len(units)):
        if assigned[i] or not vectors[i]:
            continue
        member_indices = [i]
        assigned[i] = True
        for j in range(i + 1, len(units)):
            if assigned[j] or not vectors[j]:
                continue
            if cosine_similarity(vectors[i], vectors[j]) >= similarity_threshold:
                member_indices.append(j)
                assigned[j] = True

        members = [units[idx] for idx in member_indices]
        theme, cohesion = _summarize_cluster(members, vectors, member_indices)
        clusters.append(DriftUnitCluster(theme=theme, units=members, cohesion=cohesion))

    for i, unit in enumerate(units):
        if assigned[i]:
            continue
        key = focus_bucket(unit.focus)
        theme = unit.focus or key
        clusters.append(DriftUnitCluster(theme=theme, units=[unit], cohesion=1.0))

    return clusters


def _summarize_cluster(
    members: list[MemoryUnit],
    vectors: list[list[float]],
    indices: list[int],
) -> tuple[str, float]:
    if not members:
        return "（未命名）", 0.0
    if len(members) == 1:
        focus = members[0].focus
        return focus or focus_bucket(focus), 1.0

    member_vectors = [vectors[i] for i in indices if vectors[i]]
    if not member_vectors:
        focus = members[0].focus
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
    theme = medoid.focus or focus_bucket(medoid.focus)
    return theme, cohesion
