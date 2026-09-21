"""图感知结构化查询改写：主产物是种子级信号，不只是干净文本。

消费契约（graph 侧接线时映射，infra 层不认识 KG）：
- ``entities``  → SeedResolver 精确种子（实体词面匹配，取代关键词命中固定 0.55 粗分）
- ``query``     → 向量路（embed_query 的输入）
- ``terms``     → 关键词路 / wander focus_keywords / BM25
- ``time_window``/``days`` → activation 时间过滤
- ``frame``     → 检索 profile 提示（recall / verify / …，后续分流）

命中反馈：检索方拿到结果后调 ``report(result, hits)`` 喂给成长引擎
（growth.py 用它判断模板低效并唤醒 LLM 造新模板）。
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from infra.retrieval.templates import (
    ENTITY_POS_PREFIX,
    RewriteTemplate,
    TemplateStore,
)
from infra.retrieval.tokenizer import backend as tokenizer_backend
from infra.retrieval.tokenizer import tokenize

# 时间词 → 归一标签/窗口天数（小而确定；覆盖常见口语指代）
_TIME_RULES: tuple[tuple[re.Pattern, str, int], ...] = (
    (re.compile(r"今天|今晚|现在"), "today", 1),
    (re.compile(r"昨天|昨晚"), "yesterday", 2),
    (re.compile(r"前天"), "two_days_ago", 3),
    (re.compile(r"这周|本周"), "this_week", 7),
    (re.compile(r"上周|上星期"), "last_week", 14),
    (re.compile(r"上次|最近|前几?天|之前"), "recent", 30),
    (re.compile(r"上个月|上月"), "last_month", 60),
    (re.compile(r"去年|以前|当年"), "long_ago", 365),
)

_MAX_ENTITIES = 8
_MAX_TERMS = 24


@dataclass(frozen=True)
class HitSignal:
    """通用命中信号：检索方把 ScoredUnit/RetrieveHit 等映射成 (id, score)。"""

    id: str
    score: float


@dataclass
class RewriteResult:
    query: str
    original: str
    terms: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    time_window: str = ""
    time_window_days: int | None = None
    frame: str = "general"
    template_id: str = ""
    dropped_terms: list[str] = field(default_factory=list)
    backend: str = "fallback"
    used_original_fallback: bool = False

    @property
    def hit_score(self) -> float:
        """便捷信号：是否产出了可用的种子级内容。"""
        return 1.0 if (self.entities or self.terms) else 0.0


@runtime_checkable
class QueryRewriter(Protocol):
    def rewrite(self, text: str, *, intent: str = "recall") -> RewriteResult: ...

    def report(self, result: RewriteResult, hits: list[HitSignal]) -> None: ...


def extract_time_window(text: str) -> tuple[str, int | None]:
    for pattern, label, days in _TIME_RULES:
        if pattern.search(text):
            return label, days
    return "", None


class TemplateRewriter:
    """L0 模板改写：免费、确定性、<1ms（jieba 首载除外，链路内懒加载）。"""

    def __init__(
        self,
        store: TemplateStore | None = None,
        *,
        growth=None,
        cache_size: int = 512,
    ) -> None:
        self._store = store if store is not None else TemplateStore()
        self._growth = growth
        self._cache: OrderedDict[tuple[str, str], RewriteResult] = OrderedDict()
        self._cache_size = max(0, cache_size)

    @property
    def store(self) -> TemplateStore:
        return self._store

    # ── 改写 ────────────────────────────────────────────────────────────────

    def rewrite(self, text: str, *, intent: str = "recall") -> RewriteResult:
        raw = str(text or "").strip()
        if not raw:
            return RewriteResult(query="", original=raw, backend=tokenizer_backend())
        key = (intent, raw)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        template, match = self._select_template(raw)
        stripped = self._strip_frame(raw, template, match)
        terms, dropped = self._filter_terms(stripped, template)
        entities = self._extract_entities(stripped, template, match, terms)
        # query 保留剥框架后的原文表层：文本匹配层（BM25/字符 bigram）自行切词，
        # 改写器丢词反而抹掉跨词 bigram（消融矩阵证实 -0.067）；
        # terms/entities 才是给图路的"干净信号"。
        query = " ".join(stripped.split())
        used_fallback = False
        if len(query) <= 1:
            # 空/单字符残渣（如纯框架句剥完只剩"吗"）比原文更糟 → 回退
            query = raw
            used_fallback = True
        time_label, time_days = extract_time_window(raw)

        result = RewriteResult(
            query=query,
            original=raw,
            terms=terms[:_MAX_TERMS],
            entities=entities[:_MAX_ENTITIES],
            time_window=time_label,
            time_window_days=time_days,
            frame=template.frame if intent != "verify" else "verify",
            template_id=template.template_id,
            dropped_terms=dropped,
            backend=tokenizer_backend(),
            used_original_fallback=used_fallback,
        )
        self._note_use(template.template_id)
        self._cache[key] = result
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result

    def _select_template(self, text: str) -> tuple[RewriteTemplate, re.Match | None]:
        for template in self._store.active_templates():
            m = template.match(text)
            if m is not None:
                return template, m
        return self._store.get("builtin.general") or self._store.active_templates()[-1], None

    @staticmethod
    def _strip_frame(
        text: str, template: RewriteTemplate, match: re.Match | None
    ) -> str:
        """问句框架剥除：命中 span 替换为其捕获组内容（保留实体在句内）。"""
        if match is None:
            return text
        groups = [g for g in match.groups() if g]
        return text[: match.start()] + (groups[0] if groups else "") + text[match.end():]

    @staticmethod
    def _pos_dropped(pos: str, drop_pos: frozenset[str]) -> bool:
        """精确命中丢弃词性；前缀匹配处理 ud/rr/bl 等扩展形态。
        "e" 只做精确匹配——避免前缀误伤 "eng"（英文实体词性）。"""
        if pos in drop_pos:
            return True
        return any(
            pos.startswith(p)
            for p in drop_pos
            if len(p) == 1 and p not in ("e", "x") and pos != p
        )

    @staticmethod
    def _filter_terms(
        text: str, template: RewriteTemplate
    ) -> tuple[list[str], list[str]]:
        """有词性时以词性为准（中文单字内容词"猫/养/书"合法保留）；
        长度规则只对无词性的 fallback 链路生效。"""
        terms, _ = tokenize(text)
        kept: list[str] = []
        dropped: list[str] = []
        drop_words = template.drop_words
        for term in terms:
            word = term.word
            if not word or word in drop_words:
                if word:
                    dropped.append(word)
                continue
            if term.pos:
                if TemplateRewriter._pos_dropped(term.pos, template.drop_pos):
                    dropped.append(word)
                    continue
            elif len(word) < template.min_term_len:
                dropped.append(word)
                continue
            if word not in kept:
                kept.append(word)
        return kept, dropped

    @staticmethod
    def _extract_entities(
        stripped: str,
        template: RewriteTemplate,
        match: re.Match | None,
        terms: list[str],
    ) -> list[str]:
        """实体 = 模板捕获组 + 实体词性内容词（去重、保持出现顺序）。"""
        entities: list[str] = []
        if match is not None:
            for group in match.groups():
                if group and group.strip() and group.strip() not in entities:
                    entities.append(group.strip())
        tokenized, _ = tokenize(stripped)
        for term in tokenized:
            if term.pos and term.pos.startswith(ENTITY_POS_PREFIX):
                word = term.word.strip()
                is_cjk = bool(word) and "\u4e00" <= word[0] <= "\u9fff"
                min_len = 1 if is_cjk else max(2, template.min_term_len)
                if len(word) >= min_len and word not in entities:
                    entities.append(word)
        return entities

    # ── 反馈 ────────────────────────────────────────────────────────────────

    def report(self, result: RewriteResult, hits: list[HitSignal]) -> None:
        if self._growth is None:
            return
        try:
            self._growth.report(result, hits)
        except Exception:
            pass

    def _note_use(self, template_id: str) -> None:
        if self._growth is None:
            return
        try:
            self._growth.note_use(template_id)
        except Exception:
            pass
