"""KMeans 入口快速定位：检索管线前置的"先路由到语义邻域，再进图遍历"。

规模检测：N > scale_threshold（默认 1 万）→ numpy kmeans（K=centers，默认
1000，k-means++ 初始化、固定种子、单位归一后 Lloyd 迭代——质心距离即余弦
语义）；N ≤ 阈值 → flat 模式（不聚类，route 返回全量 id，行为透明）。

数据层无关：只认 (id, vector)。未 fit 时 route 返回空列表且 status 显式
暴露（不静默降级）；增量超过漂移阈值可由调用方触发重建（可注入 enqueue
走后台线程，照 ClusterIndex.bind_enqueue 惯例）。
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class LocatorConfig:
    enabled: bool = True
    scale_threshold: int = 10_000  # N 超过才启用 kmeans；否则 flat 直通
    centers: int = 1000            # 质心数（kmeans 模式）
    probe_top_m: int = 4           # 命中最近几个质心，成员并集作为候选子集
    max_iter: int = 50
    seed: int = 0
    refit_drift_ratio: float = 0.1  # 增量成员占比超过该值 → 建议重建


class SemanticLocator:
    """向量空间入口路由器：flat（小规模直通）/ kmeans（大规模邻域定位）。"""

    def __init__(
        self,
        cfg: LocatorConfig | None = None,
        *,
        persist_path: str | Path | None = None,
    ) -> None:
        self._cfg = cfg or LocatorConfig()
        self._persist_path = Path(persist_path) if persist_path else None
        self._mode: str = "empty"  # empty | flat | kmeans
        self._ids: list[str] = []
        self._centroids: list[list[float]] = []   # kmeans 模式
        self._members: list[list[str]] = []       # 质心 → 成员 id
        self._id_to_centroid: dict[str, int] = {}
        self._fitted_n: int = 0
        self._added_since_fit: int = 0

    # ── 构建 ────────────────────────────────────────────────────────────────

    def fit(self, entries: list[tuple[str, list[float]]]) -> None:
        """entries: [(id, vector)]。规模检测决定 flat / kmeans。"""
        valid = [(str(i), v) for i, v in entries if v]
        self._ids = [i for i, _ in valid]
        self._fitted_n = len(valid)
        self._added_since_fit = 0
        if self._fitted_n == 0:
            self._mode = "empty"
            self._centroids = []
            self._members = []
            self._id_to_centroid = {}
            return
        if self._fitted_n <= self._cfg.scale_threshold:
            self._mode = "flat"
            self._centroids = []
            self._members = []
            self._id_to_centroid = {}
            return
        self._build_kmeans(valid)
        self._persist()

    def _build_kmeans(self, valid: list[tuple[str, list[float]]]) -> None:
        import numpy as np

        cfg = self._cfg
        n = len(valid)
        k = max(1, min(cfg.centers, n))
        matrix = np.array([v for _, v in valid], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        matrix = matrix / norms  # 单位归一：质心距离 ≈ 余弦语义

        rng = np.random.default_rng(cfg.seed)
        # k-means++ 初始化
        centroids = np.empty((k, matrix.shape[1]), dtype=np.float32)
        first = int(rng.integers(n))
        centroids[0] = matrix[first]
        closest_sq = np.sum((matrix - centroids[0]) ** 2, axis=1)
        for ki in range(1, k):
            total = float(closest_sq.sum())
            if total <= 1e-12:
                idx = int(rng.integers(n))
            else:
                probs = closest_sq / total
                idx = int(rng.choice(n, p=probs))
            centroids[ki] = matrix[idx]
            dist_sq = np.sum((matrix - centroids[ki]) ** 2, axis=1)
            closest_sq = np.minimum(closest_sq, dist_sq)

        assign = np.zeros(n, dtype=np.int64)
        for _ in range(cfg.max_iter):
            sims = matrix @ centroids.T  # 归一后点积即余弦
            new_assign = np.argmax(sims, axis=1)
            if np.array_equal(new_assign, assign) and _ > 0:
                break
            assign = new_assign
            for ki in range(k):
                member_vecs = matrix[assign == ki]
                if len(member_vecs):
                    centroids[ki] = member_vecs.mean(axis=0)
                    norm = float(np.linalg.norm(centroids[ki]))
                    if norm > 0:
                        centroids[ki] /= norm
                else:
                    centroids[ki] = matrix[int(rng.integers(n))]

        sims = matrix @ centroids.T
        assign = np.argmax(sims, axis=1)
        self._mode = "kmeans"
        self._centroids = [c.astype(float).tolist() for c in centroids]
        self._members = [[] for _ in range(k)]
        self._id_to_centroid = {}
        for (node_id, _), ci in zip(valid, assign):
            self._members[int(ci)].append(node_id)
            self._id_to_centroid[node_id] = int(ci)
        logger.info(
            "[retrieval.locator] kmeans fitted: n=%d k=%d", n, k
        )

    # ── 增量与重建 ──────────────────────────────────────────────────────────

    def add(self, node_id: str, vector: list[float]) -> None:
        """增量节点：flat 模式直接记账；kmeans 模式就近分配质心。"""
        node_id = str(node_id)
        if not vector:
            return
        if self._mode == "flat":
            if node_id not in set(self._ids):
                self._ids.append(node_id)
                self._added_since_fit += 1
            return
        if self._mode != "kmeans":
            return
        if node_id in self._id_to_centroid:
            return
        ci = self._nearest_centroid(vector)
        self._members[ci].append(node_id)
        self._id_to_centroid[node_id] = ci
        self._ids.append(node_id)
        self._added_since_fit += 1

    def should_refit(self) -> bool:
        if self._mode == "empty" or self._fitted_n == 0:
            return False
        return self._added_since_fit > max(
            8, int(self._fitted_n * self._cfg.refit_drift_ratio)
        )

    # ── 查询路由 ────────────────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        return self._mode != "empty"

    def route(self, query_vector: list[float], *, top_m: int | None = None) -> list[str]:
        """query → 最近 top_m 质心的成员并集（flat 模式返回全量 id）。"""
        if not query_vector or self._mode == "empty":
            return []
        if self._mode == "flat":
            return list(self._ids)
        m = top_m if top_m is not None else self._cfg.probe_top_m
        m = max(1, min(m, len(self._centroids)))
        scored = [
            (self._cosine(query_vector, c), ci)
            for ci, c in enumerate(self._centroids)
        ]
        scored.sort(reverse=True)
        out: list[str] = []
        seen: set[str] = set()
        for _, ci in scored[:m]:
            for node_id in self._members[ci]:
                if node_id not in seen:
                    seen.add(node_id)
                    out.append(node_id)
        return out

    def status(self) -> dict:
        return {
            "mode": self._mode,
            "n": len(self._ids),
            "centers": len(self._centroids) if self._mode == "kmeans" else 0,
            "fitted_n": self._fitted_n,
            "added_since_fit": self._added_since_fit,
            "should_refit": self.should_refit(),
        }

    # ── 持久化 ──────────────────────────────────────────────────────────────

    def _persist(self) -> None:
        if self._persist_path is None or self._mode == "empty":
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "mode": self._mode,
                "ids": self._ids,
                "centroids": self._centroids,
                "members": self._members,
                "id_to_centroid": self._id_to_centroid,
                "fitted_n": self._fitted_n,
            }
            self._persist_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            logger.debug("[retrieval.locator] persist failed", exc_info=True)

    def try_load(self) -> bool:
        if self._persist_path is None or not self._persist_path.is_file():
            return False
        try:
            payload = json.loads(self._persist_path.read_text(encoding="utf-8"))
            mode = str(payload.get("mode") or "")
            if mode not in ("flat", "kmeans"):
                return False
            self._mode = mode
            self._ids = [str(x) for x in (payload.get("ids") or [])]
            self._centroids = [list(map(float, c)) for c in (payload.get("centroids") or [])]
            self._members = [[str(x) for x in m] for m in (payload.get("members") or [])]
            self._id_to_centroid = {
                str(k): int(v) for k, v in (payload.get("id_to_centroid") or {}).items()
            }
            self._fitted_n = int(payload.get("fitted_n") or 0)
            self._added_since_fit = 0
            return self.ready
        except Exception:
            logger.debug("[retrieval.locator] load failed", exc_info=True)
            return False

    # ── 内部 ────────────────────────────────────────────────────────────────

    def _nearest_centroid(self, vector: list[float]) -> int:
        best_ci, best_sim = 0, -math.inf
        for ci, c in enumerate(self._centroids):
            sim = self._cosine(vector, c)
            if sim > best_sim:
                best_sim, best_ci = sim, ci
        return best_ci

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na > 0 and nb > 0 else 0.0
