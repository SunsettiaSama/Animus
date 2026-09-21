"""语义束搜索遍历：KG 检索的"流向"控制。

拿到入口种子后，不盲扩散（对比 GraphTraversal.bfs 的纯边权乘法传播），
而是让检索沿查询语义相似度最高的方向"流动"：每跳扩展 beam 内候选的
邻居，按 w_semantic·cos(query, 邻点) + w_edge·边权 打分，保留 top
beam_width 进入下一跳，累计收集至 max_nodes 预算为止。全程确定性。

数据层无关：端口只认 (to_id, weight) 边与 list[float] 节点向量，
MemoryEdgeStore / SemanticVectorIndex / 评测玩具图各自适配。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

OutEdgesFn = Callable[[str], list[tuple[str, float]]]
NodeVectorFn = Callable[[str], list[float] | None]


@dataclass(frozen=True)
class WalkHit:
    node_id: str
    score: float
    hop: int


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


class SemanticBeamWalker:
    """束搜索游走：seeds → 沿语义方向逐跳流动 → 收集节点（预算封顶）。"""

    def __init__(
        self,
        out_edges: OutEdgesFn,
        node_vector: NodeVectorFn,
        *,
        beam_width: int = 3,
        max_nodes: int = 10,
        w_semantic: float = 0.6,
        w_edge: float = 0.4,
        hop_decay: float = 0.05,
        min_step_score: float = 0.0,
    ) -> None:
        self._out_edges = out_edges
        self._node_vector = node_vector
        self._beam_width = max(1, beam_width)
        self._max_nodes = max(1, max_nodes)
        self._w_semantic = w_semantic
        self._w_edge = w_edge
        self._hop_decay = hop_decay
        self._min_step = min_step_score

    def walk(self, query_vector: list[float], seeds: dict[str, float]) -> list[WalkHit]:
        """seeds: {node_id: seed_score}；返回按累计分降序的 WalkHit（含种子自身）。

        无 query_vector 时退化为边权驱动的纯图游走（语义项为 0）。
        """
        if not seeds:
            return []
        collected: dict[str, WalkHit] = {}
        beam: list[tuple[str, float, int]] = []
        for node_id, seed_score in sorted(
            seeds.items(), key=lambda kv: (-kv[1], kv[0])
        )[: self._beam_width]:
            beam.append((node_id, float(seed_score), 0))
            if node_id not in collected or collected[node_id].score < seed_score:
                collected[node_id] = WalkHit(node_id, float(seed_score), 0)
            if len(collected) >= self._max_nodes:
                return self._finish(collected)
        visited = {node_id for node_id, _, _ in beam}

        while beam and len(collected) < self._max_nodes:
            candidates: list[tuple[float, str, int]] = []
            for node_id, parent_score, hop in beam:
                for to_id, edge_weight in self._out_edges(node_id):
                    if to_id in visited:
                        continue
                    sem = _cosine(query_vector, self._node_vector(to_id) or [])
                    edge_w = max(0.0, min(float(edge_weight), 1.0))
                    step = (
                        self._w_semantic * sem
                        + self._w_edge * edge_w
                        - self._hop_decay * (hop + 1)
                    )
                    if step < self._min_step:
                        continue
                    candidates.append((parent_score + step, to_id, hop + 1))
            if not candidates:
                break
            # 确定性排序：分数降序，同分按 node_id
            candidates.sort(key=lambda c: (-c[0], c[1]))
            next_beam: list[tuple[str, float, int]] = []
            for score, to_id, hop in candidates:
                if to_id in visited:
                    continue
                visited.add(to_id)
                if to_id not in collected or collected[to_id].score < score:
                    collected[to_id] = WalkHit(to_id, score, hop)
                next_beam.append((to_id, score, hop))
                if len(next_beam) >= self._beam_width:
                    break
                if len(collected) >= self._max_nodes:
                    break
            beam = next_beam
        return self._finish(collected)

    def _finish(self, collected: dict[str, WalkHit]) -> list[WalkHit]:
        hits = sorted(collected.values(), key=lambda h: (-h.score, h.node_id))
        return hits[: self._max_nodes]
