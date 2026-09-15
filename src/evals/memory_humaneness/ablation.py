"""消融实验：把 graph 记忆管线拆成独立检索策略，同题对比。

四条消融臂（共享同一 KG 存储，只差 recall 的评分函数）：

- ``kg_semantic``   纯语义：向量余弦（真实 EmbeddingService 若配置；否则
                    TF-IDF 字符 bigram 代理——确定性可跑，接口同构可升级）
- ``kg_bm25``       纯词面：BM25（中文按字符 bigram 切分，k1=1.5 b=0.75）
- ``kg_spread``     扩散激活：BM25 种子 → 沿实体共现边 BFS（hop_decay=0.7）
- ``kg_interfere``  干扰注入：BM25 + 情感强度加成（×(1+0.5·情绪烈度)）
                    + 关联扰动（复用 emergent.spread.associative 的
                    perturb_vector / sample_associative_intensity）

边的构建：ingest 时与既有节点做实体共现重叠（共享 bigram 比例 ≥0.15 连边，
权重=重叠度）——确定性、无 LLM，是对"知识图谱的边"的最小忠实模拟。

全部臂满足 MemoryBasePort（ingest/recall/search），可直接挂进
L2/L4 检索评测与对话管线做消融。每臂无 LLM 调用（语义臂的 embedder
除外，且默认离线代理）。
"""
from __future__ import annotations

import logging
import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field

from agent.soul.memory.emotion_intensity import infer_emotion_intensity
from agent.soul.memory.emergence.spread.associative import (
    perturb_vector,
    sample_associative_intensity,
)
from agent.soul.memory.graph.networks.block import MemoryBlock
from agent.soul.memory.graph.scored import ScoredUnit

log = logging.getLogger("evals.memory_humaneness")


class BGEEmbedder:
    """本地 BGE（infra.embedding.EmbeddingService）的消融适配器。

    - query 走 ``embed_query``（带 'query: ' 前缀），节点走 ``embed_passage``
      （BGE 的非对称检索约定）；
    - 懒加载：首次调用才加载模型（默认 local models/embedding_model）；
    - 失败抛原异常，由工厂决定是否降级 TF-IDF 代理。
    """

    def __init__(self, *, model_path: str | None = None, device: str = "auto") -> None:
        self._model_path = model_path
        self._device = device
        self._service = None

    def _ensure(self):
        if self._service is None:
            from config.soul.memory.infra_config import SoulMemoryInfraConfig
            from infra.embedding import EmbeddingService

            cfg = SoulMemoryInfraConfig.load_default()
            path = self._model_path or cfg.model_name_or_path
            self._service = EmbeddingService(
                model_name_or_path=path, device=self._device,
                query_prefix=cfg.query_prefix, passage_prefix=cfg.passage_prefix,
            )
            self._service.warm_up()
        return self._service

    def embed_query(self, text: str) -> list[float]:
        return self._ensure().embed_query(text)

    def embed_passage(self, text: str) -> list[float]:
        return self._ensure().embed_passage(text)


# ── 文本处理 ──────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文按字、英文按词，再拼 bigram——无分词器时的确定性切分。"""
    units = _TOKEN_RE.findall(text.lower())
    if len(units) == 1:
        return list(units)
    return [units[i] + units[i + 1] for i in range(len(units) - 1)] or list(units)


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    (small, big) = (a, b) if len(a) <= len(b) else (b, a)
    dot = sum(w * big.get(t, 0.0) for t, w in small.items())
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: dict[str, float] = defaultdict(float)
    for t in tokens:
        tf[t] += 1.0
    total = sum(tf.values()) or 1.0
    return {t: (c / total) * idf.get(t, 1.0) for t, c in tf.items()}


# ── 共享 KG 存储 ──────────────────────────────────────────────────────────

@dataclass
class KGNode:
    id: str
    text: str
    focus: str
    emotion: str
    valence: str
    days_ago: float
    role: str
    tokens: list[str] = field(default_factory=list)
    intensity: float = 0.0
    vector: dict[str, float] = field(default_factory=dict)
    embedding_real: list[float] | None = None  # 真实 BGE 段向量（懒计算缓存）


class KGStore:
    """消融臂共享的节点+边存储（每条用例全新实例，协议内不持久化）。"""

    def __init__(self, *, edge_threshold: float = 0.10) -> None:
        self.nodes: list[KGNode] = []
        self.edges: list[tuple[int, int, float]] = []  # (i, j, weight)
        self._edge_threshold = edge_threshold
        self._idf: dict[str, float] = {}

    def ingest(self, text: str, *, focus: str = "", emotion: str = "",
               valence: str = "neutral", days_ago: float | None = None,
               role: str = "fact") -> str:
        tokens = tokenize(text)
        node = KGNode(
            id=f"kg-{len(self.nodes)}",
            text=text, focus=focus or text[:16], emotion=emotion,
            valence=valence, days_ago=float(days_ago or 0.0), role=role,
            tokens=tokens,
            intensity=infer_emotion_intensity(emotion, text),
        )
        self.nodes.append(node)
        self._recompute_idf()
        node.vector = tfidf_vector(tokens, self._idf)
        # 实体共现边：与既有节点的 bigram 重叠率
        for j, other in enumerate(self.nodes[:-1]):
            overlap = len(set(tokens) & set(other.tokens)) / max(
                1, min(len(set(tokens)), len(set(other.tokens)))
            )
            if overlap >= self._edge_threshold:
                self.edges.append((len(self.nodes) - 1, j, overlap))
                self.edges.append((j, len(self.nodes) - 1, overlap))
        return node.id

    def _recompute_idf(self) -> None:
        n = len(self.nodes)
        df: dict[str, int] = defaultdict(int)
        for node in self.nodes:
            for t in set(node.tokens):
                df[t] += 1
        self._idf = {
            t: math.log(1.0 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()
        }

    def bm25_scores(self, query: str) -> dict[int, float]:
        q_tokens = tokenize(query)
        scores: dict[int, float] = {}
        avgdl = (sum(len(n.tokens) for n in self.nodes) / len(self.nodes)) if self.nodes else 1.0
        df: dict[str, int] = defaultdict(int)
        for node in self.nodes:
            for t in set(node.tokens):
                df[t] += 1
        k1, b = 1.5, 0.75
        for i, node in enumerate(self.nodes):
            tf: dict[str, int] = defaultdict(int)
            for t in node.tokens:
                tf[t] += 1
            score = 0.0
            for t in q_tokens:
                if tf.get(t):
                    idf = math.log(1.0 + (len(self.nodes) - df[t] + 0.5) / (df[t] + 0.5))
                    score += idf * tf[t] * (k1 + 1) / (
                        tf[t] + k1 * (1 - b + b * len(node.tokens) / avgdl)
                    )
            if score > 0:
                scores[i] = score
        return scores

    def neighbors(self, idx: int) -> list[tuple[int, float]]:
        return [(j, w) for (i, j, w) in self.edges if i == idx]

    def __len__(self) -> int:
        return len(self.nodes)


# ── 消融臂基类 ────────────────────────────────────────────────────────────

class _KGAblationBase:
    """满足 MemoryBasePort 用法的消融臂骨架。"""

    kind = "kg"

    def __init__(self, store: KGStore, *, top_k_default: int = 5) -> None:
        self._store = store
        self._top_k_default = top_k_default

    def ingest(self, text: str, *, focus: str = "", emotion: str = "",
               valence: str = "neutral", interactor_id: str = "",
               tags: list[str] | None = None, meta: dict | None = None,
               days_ago: float | None = None) -> str:
        return self._store.ingest(
            text, focus=focus, emotion=emotion, valence=valence, days_ago=days_ago,
        )

    def recall(self, query: str, top_k: int = 5,
               emotional_context: str = "") -> MemoryBlock:
        ranked = self._rank(query)[:top_k]
        from .hint import with_no_memory_hint

        entries = [f"[{self.kind}] {self._store.nodes[i].focus}："
                   f"{self._store.nodes[i].text[:160]}" for i, _ in ranked]
        # 兜底：检索判空时显式提示"无相关记忆"（评测端跳过该行，另计诚实率）
        entries = with_no_memory_hint(entries)
        return MemoryBlock(label=self.kind, entries=entries)

    def search(self, mode: str, **kwargs) -> list[dict]:
        q = str(kwargs.get("query", ""))
        ranked = self._rank(q)
        return [{"id": self._store.nodes[i].id, "content": self._store.nodes[i].text,
                 "final_score": round(s, 4)} for i, s in ranked]

    def dispose(self) -> None:
        pass

    def _rank(self, query: str) -> list[tuple[int, float]]:
        raise NotImplementedError

    def _render(self, ranked: list[tuple[int, float]]) -> list[str]:
        return [f"{self._store.nodes[i].focus}：{self._store.nodes[i].text}" for i, _ in ranked]


class KGSemanticBase(_KGAblationBase):
    """纯语义：查询向量 × 节点向量 余弦。

    ``embedder`` 为 ``callable(text) -> list[float]``（真实 EmbeddingService
    或任意实现）；缺省用 TF-IDF 代理向量（确定性、离线可跑）。节点向量懒
    计算并缓存于节点对象。
    """

    kind = "kg_semantic"

    def __init__(self, store: KGStore, *, embedder=None) -> None:
        super().__init__(store)
        self._embedder = embedder
        if embedder is None:
            log.info("kg_semantic：未注入真实 Embedding，使用 TF-IDF 代理向量（确定性）")

    @staticmethod
    def _cos_list(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def _rank(self, query: str) -> list[tuple[int, float]]:
        if self._embedder is not None:
            qv = (self._embedder.embed_query(query)
                  if hasattr(self._embedder, "embed_query") else self._embedder(query))
            scored = []
            for i, n in enumerate(self._store.nodes):
                if n.embedding_real is None:
                    n.embedding_real = (
                        self._embedder.embed_passage(n.text)
                        if hasattr(self._embedder, "embed_passage")
                        else self._embedder(n.text)
                    )
                scored.append((i, self._cos_list(qv, n.embedding_real)))
        else:
            qv = tfidf_vector(tokenize(query), self._store._idf)
            scored = [(i, cosine(qv, n.vector)) for i, n in enumerate(self._store.nodes)]
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


class KGBM25Base(_KGAblationBase):
    """纯词面：BM25。"""

    kind = "kg_bm25"

    def _rank(self, query: str) -> list[tuple[int, float]]:
        scored = self._store.bm25_scores(query)
        out = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        return out


class KGSpreadBase(_KGAblationBase):
    """扩散激活：BM25 种子 → 实体共现边 BFS（hop_decay=0.7，≤2 跳）。"""

    kind = "kg_spread"

    def __init__(self, store: KGStore, *, seed_top_k: int = 3,
                 hop_decay: float = 0.7, max_hops: int = 2) -> None:
        super().__init__(store)
        self._seed_top_k = seed_top_k
        self._decay = hop_decay
        self._max_hops = max_hops

    def _rank(self, query: str) -> list[tuple[int, float]]:
        bm = self._store.bm25_scores(query)
        if not bm:
            return []
        max_s = max(bm.values())
        seeds: dict[int, float] = {
            i: s / max_s for i, s in
            sorted(bm.items(), key=lambda x: x[1], reverse=True)[: self._seed_top_k]
        }
        # BFS 传播
        best: dict[int, float] = dict(seeds)
        queue: list[tuple[int, float, int]] = [(i, s, 0) for i, s in seeds.items()]
        qi = 0
        while qi < len(queue):
            idx, score, hop = queue[qi]
            qi += 1
            if hop >= self._max_hops:
                continue
            for j, w in self._store.neighbors(idx):
                nxt = score * w * self._decay
                if nxt < 0.05:
                    continue
                if nxt > best.get(j, 0.0):
                    best[j] = nxt
                    queue.append((j, nxt, hop + 1))
        # 种子分优先，传播分补充
        out = sorted(best.items(), key=lambda x: (x[1], x[0] in seeds), reverse=True)
        return out


class KGInterfereBase(_KGAblationBase):
    """干扰注入：BM25 × 情感加成 × 关联扰动。

    复刻 graph 管线里两个"有意混淆"组件的独立贡献：
    - 情感加成：score × (1 + 0.5·情绪烈度)（与 BaseNode.activation 同系数）
    - 关联扰动：查询向量按随机强度高斯扰动后再算余弦（联想漂移）
    """

    kind = "kg_interfere"

    def __init__(self, store: KGStore, *, emotion_boost: float = 0.5,
                 assoc_weight: float = 0.35, seed: int | None = None,
                 embedder=None) -> None:
        super().__init__(store)
        self._emotion_boost = emotion_boost
        self._assoc_weight = assoc_weight
        self._embedder = embedder
        self._rng = random.Random(seed)

    @staticmethod
    def _cos_list_vec(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def _rank(self, query: str) -> list[tuple[int, float]]:
        bm = self._store.bm25_scores(query)
        if not bm:
            return []
        max_s = max(bm.values())
        bm_norm = {i: s / max_s for i, s in bm.items()}
        # 情感加成
        emotion_applied = {
            i: s * (1.0 + self._emotion_boost * self._store.nodes[i].intensity)
            for i, s in bm_norm.items()
        }
        # 关联扰动：查询向量按随机强度高斯扰动后算余弦（真实 BGE 或代理）
        intensity = sample_associative_intensity()
        if self._embedder is not None:
            qv_real = self._embedder.embed_query(query)
            perturbed = perturb_vector(qv_real, intensity, sigma=0.15)
            assoc = {}
            if perturbed:
                for i, n in enumerate(self._store.nodes):
                    if n.embedding_real is None:
                        n.embedding_real = self._embedder.embed_passage(n.text)
                    assoc[i] = self._cos_list_vec(perturbed, n.embedding_real)
        else:
            qv = tfidf_vector(tokenize(query), self._store._idf)
            perturbed = perturb_vector(
                [qv.get(t, 0.0) for t in sorted({t for n in self._store.nodes for t in n.tokens})]
                if qv else [],
                intensity, sigma=0.15,
            )
            if perturbed:
                dim_tokens = sorted({t for n in self._store.nodes for t in n.tokens})
                pv = dict(zip(dim_tokens, perturbed))
                assoc = {i: cosine(pv, n.vector) for i, n in enumerate(self._store.nodes)}
            else:
                assoc = {}
        blended: dict[int, float] = {}
        for i in set(emotion_applied) | set(assoc):
            blended[i] = (
                0.65 * emotion_applied.get(i, 0.0)
                + self._assoc_weight * assoc.get(i, 0.0)
            )
        out = sorted(blended.items(), key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in out if s > 0]



class KGDriftBase(_KGAblationBase):
    """软约束组件：硬通道（BM25 正常记忆）+ 软通道（关联扰动的联想漂移）。

    软通道召回的记忆在返回行上单独标注 ``【隐约浮现】``，并在块尾附解释
    （DRIFT_NOTE）——把"这些是隐隐约约浮现、未必相关的念头"作为软约束
    告知模型，让它以不确定口吻对待而非当作确定事实。检索对错仍由
    检索管线评测；本臂测量的是"标注呈现"对行为的影响。
    """

    kind = "kg_drift"

    def __init__(self, store: KGStore, *, seed_top_k: int = 3,
                 soft_top_k: int = 2, seed: int | None = None,
                 embedder=None) -> None:
        super().__init__(store)
        self._seed_top_k = seed_top_k
        self._soft_top_k = soft_top_k
        self._embedder = embedder
        self._rng = random.Random(seed)

    def _rank(self, query: str) -> list[tuple[int, float]]:
        raise NotImplementedError  # 双通道，见 recall

    def recall(self, query: str, top_k: int = 5,
               emotional_context: str = "") -> MemoryBlock:
        from .hint import DRIFT_NOTE, DRIFT_TAG, with_no_memory_hint

        bm = self._store.bm25_scores(query)
        max_s = max(bm.values()) if bm else 0.0
        hard = [
            i for i, s in sorted(bm.items(), key=lambda x: x[1], reverse=True)
            if s / max_s >= 0.25
        ][: self._seed_top_k]

        # 软通道：扰动向量余弦，排除硬通道已命中的
        soft: list[int] = []
        if self._embedder is not None:
            qv = self._embedder.embed_query(query)
            perturbed = perturb_vector(qv, sample_associative_intensity(), sigma=0.15)
            if perturbed:
                cand = []
                for i, n in enumerate(self._store.nodes):
                    if n.embedding_real is None:
                        n.embedding_real = self._embedder.embed_passage(n.text)
                    if i in hard:
                        continue
                    sim = self.__class__._cos_pair(perturbed, n.embedding_real)
                    if sim > 0:
                        cand.append((i, sim))
                soft = [i for i, _ in sorted(cand, key=lambda x: x[1], reverse=True)
                        [: self._soft_top_k]]

        entries = [f"{self._store.nodes[i].focus}：{self._store.nodes[i].text}"
                   for i in hard]
        if soft:
            entries += [DRIFT_NOTE]
            entries += [f"{DRIFT_TAG} {self._store.nodes[i].focus}："
                        f"{self._store.nodes[i].text}" for i in soft]
        entries = with_no_memory_hint(entries)
        return MemoryBlock(label=self.kind, entries=entries)

    def search(self, mode: str, **kwargs) -> list[dict]:
        return [{"id": n.id, "content": n.text, "final_score": 1.0}
                for n in self._store.nodes]

    @staticmethod
    def _cos_pair(a: list[float], b: list[float]) -> float:
        import math as _m
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = _m.sqrt(sum(x * x for x in a))
        nb = _m.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0



# ── 工厂 ──────────────────────────────────────────────────────────────────

def build_kg_store() -> KGStore:
    return KGStore()


def ablation_factory(kind: str, *, embedder=None, seed: int | None = None,
                     use_bge: bool = False):
    """返回 ``Callable[[], base]``——每条用例全新存储（评测协议）。

    ``use_bge=True``：语义/干扰臂装配本地 BGE（infra 配置指向
    models/embedding_model）；加载失败降级 TF-IDF 代理并告警。
    """
    kind = kind.strip().lower()
    resolved = embedder
    if use_bge and kind in ("kg_semantic", "kg_interfere", "kg_drift") and embedder is None:
        try:
            resolved = BGEEmbedder()
            resolved.embed_query("预热")  # 触发模型加载，失败即降级
            log.info("%s：已装配本地 BGE", kind)
        except Exception as exc:
            log.warning("%s：BGE 加载失败（%s），降级 TF-IDF 代理", kind, str(exc)[:80])
            resolved = None

    def _make():
        store = KGStore()
        if kind == "kg_semantic":
            return KGSemanticBase(store, embedder=resolved)
        if kind == "kg_bm25":
            return KGBM25Base(store)
        if kind == "kg_spread":
            return KGSpreadBase(store)
        if kind == "kg_interfere":
            return KGInterfereBase(store, seed=seed, embedder=resolved)
        if kind == "kg_drift":
            return KGDriftBase(store, seed=seed,
                               embedder=resolved if use_bge else None)
        raise SystemExit(f"unknown ablation kind: {kind!r}")

    return _make
