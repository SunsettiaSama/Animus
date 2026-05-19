from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agent.soul.memory.unit import MemoryUnit, Valence

if TYPE_CHECKING:
    from agent.soul.memory.short_term.manager import ShortTermMemoryManager
    from agent.soul.memory.long_term.manager import LongTermMemoryManager


# ── Backend protocols（解耦向量检索依赖）─────────────────────────────────────

@runtime_checkable
class EmbedderBackend(Protocol):
    """最小嵌入器协议，任何实现 embed() 的对象均满足。"""
    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class VectorBackend(Protocol):
    """最小向量存储协议，实现 search() 即可接入检索器。

    search() 返回 (unit_id, similarity_score) 列表，相似度 0~1。
    """
    def search(self, vector: list[float], top_k: int) -> list[tuple[str, float]]: ...


# ── 检索结果单元 ─────────────────────────────────────────────────────────────

@dataclass
class ScoredUnit:
    """带评分的记忆单元，作为所有检索模式的统一返回类型。

    字段
    ----
    unit
        原始记忆单元
    relevance
        语义相关度（向量检索时为余弦相似度；非向量检索默认 1.0）
    activation
        实时激活度（由 unit.activation() 计算，查询时注入）
    final_score
        综合得分 = relevance × activation（hybrid 模式）或直接等于 activation
    source
        记录该结果来自哪个检索层（"stm" | "ltm"），供调试和权重调整使用
    """

    unit: MemoryUnit
    relevance: float = 1.0
    activation: float = 0.0
    final_score: float = 0.0
    source: str = "ltm"   # "stm" | "ltm"

    def render_line(self, max_content: int = 80) -> str:
        """渲染为单行 prompt 注入文本。"""
        line = f"[{self.unit.MEMORY_TYPE}] {self.unit.focus}"
        for attr in ("fact", "reconstructed_fact", "narrative"):
            val = getattr(self.unit, attr, "")
            if val:
                line += f"：{val[:max_content]}"
                break
        return line


# ── MemoryRetriever ───────────────────────────────────────────────────────────

class MemoryRetriever:
    """记忆检索器，提供五种检索模式，可独立使用也可组合。

    所有模式均返回 `list[ScoredUnit]`，按 `final_score` 降序排列。

    五种模式
    --------
    recent(...)
        近期经历检索：按 last_accessed 取最近条目，可跨 STM/LTM。
        适合"最近发生了什么"类查询。

    semantic(query, ...)
        语义检索：嵌入查询文本，在向量存储中搜索相似记忆。
        需要 embedder + vector_store，否则抛出 RuntimeError。

    by_valence(valence, ...)
        情感倾向检索：按 Valence 枚举过滤（positive/negative/mixed/neutral）。
        可结合 emotion_hint 对命名情绪做二次软过滤。
        适合人格层根据当前情绪状态偏置检索。

    by_field(...)
        结构化字段检索：支持 memory_type / valence / chapter / source_id /
        emotion_contains / 时间范围等多条件 AND 组合。
        适合精确查询（如"找出所有叙事记忆"、"找出某章节"）。

    hybrid(query, ...)
        混合检索（推荐）：语义候选 × activation 重排 × 可选字段过滤。
        若无 embedder，自动降级为 recent + activation 排序。
        final_score = w_relevance × relevance + w_activation × activation

    参数
    ----
    stm
        短期记忆管理器（Redis）
    ltm
        长期记忆管理器（MySQL）
    stm_half_life_days / ltm_half_life_days
        激活度计算的半衰期，与 MemoryServiceConfig 保持一致
    embedder
        可选，满足 EmbedderBackend 协议的嵌入器实例
    vector_store
        可选，满足 VectorBackend 协议的向量存储实例
    """

    def __init__(
        self,
        stm: ShortTermMemoryManager,
        ltm: LongTermMemoryManager,
        stm_half_life_days: float = 3.0,
        ltm_half_life_days: float = 30.0,
        embedder: EmbedderBackend | None = None,
        vector_store: VectorBackend | None = None,
    ) -> None:
        self._stm = stm
        self._ltm = ltm
        self._stm_hl = stm_half_life_days
        self._ltm_hl = ltm_half_life_days
        self._embedder = embedder
        self._vector_store = vector_store

    # ── 1. 近期经历检索 ────────────────────────────────────────────────────────

    def recent(
        self,
        limit: int = 10,
        memory_type: str | None = None,
        include_stm: bool = True,
        include_ltm: bool = True,
    ) -> list[ScoredUnit]:
        """按 last_accessed 返回最近的记忆条目。

        参数
        ----
        limit
            最多返回条数
        memory_type
            限制类型（"factual" | "reconstructive" | "narrative"），None=全部
        include_stm / include_ltm
            是否纳入短期/长期记忆层
        """
        now = datetime.now(timezone.utc)
        results: list[ScoredUnit] = []

        if include_stm:
            stm_units = (
                self._stm.list_by_type(memory_type, limit=limit)
                if memory_type
                else self._stm.list_all(limit=limit)
            )
            for u in stm_units:
                act = u.activation(now=now, half_life_days=self._stm_hl)
                results.append(ScoredUnit(u, relevance=1.0, activation=act, final_score=act, source="stm"))

        if include_ltm:
            ltm_units = self._ltm.list_recent(memory_type=memory_type, limit=limit)
            for u in ltm_units:
                act = u.activation(now=now, half_life_days=self._ltm_hl)
                results.append(ScoredUnit(u, relevance=1.0, activation=act, final_score=act, source="ltm"))

        results.sort(key=lambda s: s.unit.last_accessed, reverse=True)
        return results[:limit]

    # ── 2. 语义检索 ────────────────────────────────────────────────────────────

    def semantic(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[ScoredUnit]:
        """嵌入查询文本，从向量存储检索语义最相似的记忆。

        需要 embedder 和 vector_store，未配置时抛出 RuntimeError。
        """
        if self._embedder is None or self._vector_store is None:
            raise RuntimeError(
                "semantic() 需要 embedder 和 vector_store，"
                "请在 MemoryRetriever.__init__ 中注入。"
            )
        now = datetime.now(timezone.utc)
        vector = self._embedder.embed(query)
        hits = self._vector_store.search(vector, top_k=top_k)  # [(id, score), ...]

        unit_ids = [uid for uid, _ in hits]
        score_map = {uid: score for uid, score in hits}

        units = self._ltm.get_many(unit_ids)
        results: list[ScoredUnit] = []
        for u in units:
            rel = score_map.get(u.id, 0.0)
            act = u.activation(now=now, half_life_days=self._ltm_hl)
            results.append(ScoredUnit(u, relevance=rel, activation=act, final_score=rel * act, source="ltm"))

        results.sort(key=lambda s: s.final_score, reverse=True)
        return results

    # ── 3. 情感倾向检索 ────────────────────────────────────────────────────────

    def by_valence(
        self,
        valence: Valence,
        limit: int = 10,
        emotion_hint: str = "",
        include_stm: bool = True,
        include_ltm: bool = True,
    ) -> list[ScoredUnit]:
        """按情感倾向枚举检索，可附加命名情绪软过滤。

        参数
        ----
        valence
            粗粒度情感方向（Valence.positive / negative / mixed / neutral）
        limit
            最多返回条数
        emotion_hint
            命名情绪字符串，非空时优先返回 emotion 字段包含该关键词的条目
            （软过滤：不满足的条目仍然返回，但排名靠后）
        include_stm / include_ltm
            是否纳入短期/长期记忆层
        """
        now = datetime.now(timezone.utc)
        results: list[ScoredUnit] = []

        if include_stm:
            for u in self._stm.list_by_valence(valence, limit=limit):
                act = u.activation(now=now, half_life_days=self._stm_hl)
                results.append(ScoredUnit(u, relevance=1.0, activation=act, final_score=act, source="stm"))

        if include_ltm:
            for u in self._ltm.list_recent(valence=valence, limit=limit):
                act = u.activation(now=now, half_life_days=self._ltm_hl)
                results.append(ScoredUnit(u, relevance=1.0, activation=act, final_score=act, source="ltm"))

        # emotion_hint 软过滤：命中的条目 final_score 加权
        if emotion_hint:
            for s in results:
                if emotion_hint in s.unit.emotion:
                    s.final_score = min(1.0, s.final_score * 1.3)

        results.sort(key=lambda s: s.final_score, reverse=True)
        return results[:limit]

    # ── 4. 字段检索 ────────────────────────────────────────────────────────────

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
        """多条件结构化字段查询，所有条件为 AND 关系，仅查询 LTM。

        参数
        ----
        memory_type
            记忆类型（"factual" | "reconstructive" | "narrative"）
        valence
            情感倾向枚举
        chapter
            叙事章节标签（NarrativeMemory 专属）
        source_id
            原始事实记忆 id（查找其所有重构版本）
        emotion_contains
            命名情绪关键词（LIKE %keyword%）
        created_after / created_before
            创建时间范围，格式 "YYYY-MM-DD HH:MM:SS"
        limit
            最多返回条数
        """
        now = datetime.now(timezone.utc)
        units = self._ltm.query_by_fields(
            memory_type=memory_type,
            valence=valence,
            chapter=chapter,
            source_id=source_id,
            emotion_contains=emotion_contains,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
        )
        results = []
        for u in units:
            act = u.activation(now=now, half_life_days=self._ltm_hl)
            results.append(ScoredUnit(u, relevance=1.0, activation=act, final_score=act, source="ltm"))
        results.sort(key=lambda s: s.final_score, reverse=True)
        return results

    # ── 5. 混合检索 ────────────────────────────────────────────────────────────

    def hybrid(
        self,
        query: str,
        top_k: int = 5,
        valence: Valence | None = None,
        memory_type: str | None = None,
        w_relevance: float = 0.6,
        w_activation: float = 0.4,
    ) -> list[ScoredUnit]:
        """混合检索（推荐用于 recall() 主路径）。

        流程
        ----
        1. 语义候选（若有 embedder）或近期候选（降级）
        2. 按 valence / memory_type 过滤（若指定）
        3. final_score = w_relevance × relevance + w_activation × activation
        4. 按 final_score 降序返回 top_k 条

        注意：w_relevance + w_activation 建议 = 1.0，但不强制。
        降级模式下 relevance 固定为 1.0，结果退化为纯 activation 排序。

        参数
        ----
        query
            检索查询文本（当前对话的 question 或上下文摘要）
        top_k
            最多返回条数
        valence
            情感倾向过滤（None=不过滤）
        memory_type
            类型过滤（None=不过滤）
        w_relevance / w_activation
            语义相关度和激活度的权重
        """
        now = datetime.now(timezone.utc)
        candidates: list[ScoredUnit] = []

        # ── 语义候选（优先）or 近期候选（降级）──────────────────────────────
        if self._embedder is not None and self._vector_store is not None:
            vector = self._embedder.embed(query)
            hits = self._vector_store.search(vector, top_k=top_k * 3)
            id_score = {uid: score for uid, score in hits}
            units = self._ltm.get_many(list(id_score.keys()))
            for u in units:
                act = u.activation(now=now, half_life_days=self._ltm_hl)
                rel = id_score.get(u.id, 0.0)
                candidates.append(ScoredUnit(u, relevance=rel, activation=act, source="ltm"))
        else:
            # 降级：STM + LTM 近期，relevance=1.0
            for u in self._stm.list_all(limit=top_k * 2):
                act = u.activation(now=now, half_life_days=self._stm_hl)
                candidates.append(ScoredUnit(u, relevance=1.0, activation=act, source="stm"))
            for u in self._ltm.list_recent(limit=top_k * 2):
                act = u.activation(now=now, half_life_days=self._ltm_hl)
                candidates.append(ScoredUnit(u, relevance=1.0, activation=act, source="ltm"))

        # ── 字段过滤 ────────────────────────────────────────────────────────
        if valence is not None:
            candidates = [s for s in candidates if s.unit.valence == valence]
        if memory_type is not None:
            candidates = [s for s in candidates if s.unit.MEMORY_TYPE == memory_type]

        # ── 加权评分 ────────────────────────────────────────────────────────
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
        """Life 叙事连续性：混合检索 + 重排后按相关度与分差筛选。

        流程
        ----
        1. hybrid 拉 candidate_k 条并重排（语义 × 激活）
        2. 首条 relevance 低于 min_relevance → 空（与任务无关则不注入）
        3. 首条 final_score 低于 min_final_score → 空（降级模式保底）
        4. 仅保留 final_score >= top - max_score_gap 的条目，最多 top_k 条
        """
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

    # ── 6. 心理漂移式检索（走神/闪现）───────────────────────────────────────

    def wander(
        self,
        n: int = 2,
        emotion_weight: float = 0.5,
        rehearsal_weight: float = 0.3,
        noise: float = 0.2,
        include_stm: bool = True,
        include_ltm: bool = True,
        ltm_limit: int = 60,
        focus_keywords: list[str] | None = None,
        keyword_boost: float = 0.28,
    ) -> list[ScoredUnit]:
        """心理漂移式检索：不需要查询文本，记忆自发"闪现"。

        模拟非自愿记忆（Involuntary Autobiographical Memory）：
        记忆不因主动搜索而浮现，而是由自身的"冲动权重"决定是否跃入意识。

        权重模型
        --------
        每条记忆的浮现概率由三个成分加权：

            salience = emotion_weight  × emotion_intensity    # 情绪烈度
                     + rehearsal_weight × rehearsal_score      # 反刍次数（对数压缩）
                     + noise            × U(0, 1)              # 随机扰动

        其中 rehearsal_score = log(1 + rehearsal_count) / log(1 + max_rehearsal)
        归一化后保证不同量级的数据可比。

        心理学依据
        ----------
        - 情绪烈度（Berntsen 2009）：情感强烈的记忆更容易非自愿浮现
        - 反刍次数（Nolen-Hoeksema 1991）：被反复"咀嚼"的记忆形成侵入性思维
        - 随机噪声：模拟"为什么偏偏想到这个"的不可预测性，也防止总是返回相同记忆

        采样机制
        --------
        **非 top-n，而是加权随机采样（weighted random sampling without replacement）**

        这是与其他五种检索模式的本质区别：确定性模式总是返回最高分，
        而 wander() 是概率性的——权重只影响被选中的概率，不保证高分必中。
        这让同样的心跳时机每次触发不同的记忆闪现，更接近真实的走神体验。

        参数
        ----
        n
            本次"走神"中闪现的记忆数量（通常 1~3 条）
        emotion_weight
            情绪烈度在 salience 中的权重
        rehearsal_weight
            反刍次数在 salience 中的权重
        noise
            随机扰动强度；值越大，结果越不可预测，越低则越偏向高情绪记忆
        include_stm / include_ltm
            是否从 STM/LTM 中取候选
        ltm_limit
            从 LTM 中拉取的候选条数（基于最近访问时间；不做向量检索）
        """
        now = datetime.now(timezone.utc)
        candidates: list[ScoredUnit] = []

        if include_stm:
            for u in self._stm.list_all(limit=200):
                act = u.activation(now=now, half_life_days=self._stm_hl)
                candidates.append(ScoredUnit(u, relevance=1.0, activation=act, source="stm"))

        if include_ltm:
            for u in self._ltm.list_recent(limit=ltm_limit):
                act = u.activation(now=now, half_life_days=self._ltm_hl)
                candidates.append(ScoredUnit(u, relevance=1.0, activation=act, source="ltm"))

        if not candidates:
            return []

        # ── 计算 salience ────────────────────────────────────────────────────
        max_rehearsal = max(s.unit.rehearsal_count for s in candidates) or 1

        saliences: list[float] = []
        for s in candidates:
            u = s.unit
            rehearsal_score = math.log1p(u.rehearsal_count) / math.log1p(max_rehearsal)
            raw = (
                emotion_weight   * u.emotion_intensity
                + rehearsal_weight * rehearsal_score
                + noise            * random.random()
            )
            if focus_keywords:
                hay = _memory_unit_keyword_haystack(u).lower()
                if any(k.strip() and k.strip().lower() in hay for k in focus_keywords):
                    raw += keyword_boost
            saliences.append(max(raw, 1e-6))   # 保证每条记忆都有非零被选中概率

        # ── 加权随机采样（无放回）───────────────────────────────────────────
        k = min(n, len(candidates))
        chosen_indices = _weighted_sample_without_replacement(saliences, k)

        results: list[ScoredUnit] = []
        for idx in chosen_indices:
            s = candidates[idx]
            s.final_score = saliences[idx]
            results.append(s)

        return results

    # ── 辅助：渲染为 prompt 块 ───────────────────────────────────────────────

    def render_block(
        self,
        scored: list[ScoredUnit],
        label: str = "记忆参考",
        max_content: int = 80,
    ) -> str:
        """将 ScoredUnit 列表渲染为 prompt-ready 文本块。"""
        if not scored:
            return ""
        lines = [f"[{label}]"] + [s.render_line(max_content) for s in scored]
        return "\n".join(f"- {l}" if i > 0 else l for i, l in enumerate(lines))


def _memory_unit_keyword_haystack(unit: MemoryUnit) -> str:
    chunks = [
        unit.focus,
        getattr(unit, "fact", "") or "",
        getattr(unit, "perception", "") or "",
        getattr(unit, "reconstructed_fact", "") or "",
        getattr(unit, "narrative", "") or "",
    ]
    return " ".join(str(c) for c in chunks if c)


# ── 模块级辅助 ──────────────────────────────────────────────────────────────

def _weighted_sample_without_replacement(
    weights: list[float], k: int
) -> list[int]:
    """返回 k 个不重复的下标，按权重概率采样（蓄水池算法变体）。

    使用 Efraimidis-Spirakis 算法（2006）：
        key_i = U(0,1)^(1/weight_i)
    取 key 最大的 k 个下标，等价于加权无放回采样。

    复杂度 O(n log n)，实现简洁且理论正确。
    """
    if k <= 0 or not weights:
        return []
    keys = [random.random() ** (1.0 / w) for w in weights]
    indexed = sorted(enumerate(keys), key=lambda x: x[1], reverse=True)
    return [i for i, _ in indexed[:k]]
