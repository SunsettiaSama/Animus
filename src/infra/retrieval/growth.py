"""成长型模板引擎：命中反馈统计 → 低效唤醒 LLM 造新模板 → trial/退役。

判据是图路命中（种子是否导致检索命中），不是文本相似。造出的新模板
schema 强制：patterns 非空、可编译、且至少一个 pattern 带捕获组
（实体抽取是图检索的种子来源，纯剥除式模板不收）。

无 LLM 构造 = 纯统计模式（惰性）；一切异常吞在内部，绝不外溢到检索主链路。
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from infra.retrieval.rewriter import HitSignal, RewriteResult
from infra.retrieval.templates import RewriteTemplate, TemplateStore
from infra.threading import ThreadLease, get_thread_registry

logger = logging.getLogger(__name__)

_WAKE_POLL_SEC = 0.5
_MAX_LOW_EXAMPLES = 6
_MAX_DROPPED_SHOWN = 8


class AuthorLLM(Protocol):
    def generate(self, prompt: str) -> str: ...


@dataclass
class GrowthConfig:
    enabled: bool = True
    # 生产默认关（PRD R4.2 统计先行）：开启还需注入 LLM 才实际造模板
    authoring_enabled: bool = False
    # 平均命中分低于该阈值视为低效（滚动窗口）
    hit_threshold: float = 0.25
    min_samples: int = 20
    cooldown_minutes: float = 30.0
    # grown 模板持续低于该分则退役
    retire_threshold: float = 0.10
    max_templates: int = 64


@dataclass
class TemplateStats:
    uses: int = 0
    reports: int = 0
    hit_count: int = 0  # 有命中（score>0）的反馈次数
    score_sum: float = 0.0
    low_streak: int = 0
    last_authored_ts: float = 0.0

    @property
    def avg_score(self) -> float:
        return self.score_sum / self.reports if self.reports else 0.0

    def to_dict(self) -> dict:
        return {
            "uses": self.uses,
            "reports": self.reports,
            "hit_count": self.hit_count,
            "score_sum": round(self.score_sum, 4),
            "low_streak": self.low_streak,
            "last_authored_ts": self.last_authored_ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateStats":
        return cls(
            uses=int(data.get("uses") or 0),
            reports=int(data.get("reports") or 0),
            hit_count=int(data.get("hit_count") or 0),
            score_sum=float(data.get("score_sum") or 0.0),
            low_streak=int(data.get("low_streak") or 0),
            last_authored_ts=float(data.get("last_authored_ts") or 0.0),
        )


_AUTHOR_PROMPT = """你是检索查询改写模板的"成长引擎"。下面是一个低效模板的画像：
- 模板定义（JSON）：{template_json}
- 近期低命中例子（原文 → 改写后 query / 实体 → 检索结果）：
{examples}

请针对这些失败模式设计一个新模板，要求：
1. patterns：1-3 个 Python 正则（re.search 语义），必须至少一个含捕获组，捕获组抓"实体/话题"；
2. drop_words：需要丢弃的低贡献词列表（可为空）；
3. frame：从 general/recall/quote/topic/time/verify 中选一个；
4. 只输出 JSON 对象，不要解释文字。

输出格式：
{{"name": "模板名", "patterns": ["正则…"], "drop_words": ["词…"], "frame": "recall"}}"""


class GrowthEngine:
    """统计 + 阈值触发 + 后台 LLM 造模板（ThreadLease FIFO，owner=infra.retrieval.growth）。"""

    def __init__(
        self,
        store: TemplateStore,
        *,
        llm: AuthorLLM | None = None,
        cfg: GrowthConfig | None = None,
        stats_path: str | None = None,
    ) -> None:
        self._store = store
        self._llm = llm
        self._cfg = cfg or GrowthConfig()
        self._stats: dict[str, TemplateStats] = {}
        self._examples: dict[str, list[tuple[str, str, bool]]] = {}
        self._lock = threading.Lock()
        self._tasks: list[str] = []  # 待造模板的 template_id 队列
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lease: ThreadLease | None = None
        self._stats_path = stats_path
        self._load_stats()

    @property
    def cfg(self) -> GrowthConfig:
        return self._cfg

    # ── 反馈入口（检索主链路调用，永不 raise） ──────────────────────────────

    def note_use(self, template_id: str) -> None:
        if not self._cfg.enabled:
            return
        with self._lock:
            stats = self._stats.setdefault(template_id, TemplateStats())
            stats.uses += 1

    def report(self, result: RewriteResult, hits: list[HitSignal]) -> None:
        """hits：本条改写导致的检索命中（score>0 记命中）。"""
        if not self._cfg.enabled or not result.template_id:
            return
        scores = [h.score for h in hits if isinstance(h, HitSignal)]
        mean = sum(scores) / len(scores) if scores else 0.0
        tid = result.template_id
        with self._lock:
            stats = self._stats.setdefault(tid, TemplateStats())
            stats.reports += 1
            stats.score_sum += mean
            if scores:
                stats.hit_count += 1
                stats.low_streak = 0
            else:
                stats.low_streak += 1
            examples = self._examples.setdefault(tid, [])
            examples.append((result.original[:80], result.query[:80], bool(scores)))
            del examples[:-_MAX_LOW_EXAMPLES]
            self._maybe_enqueue_locked(tid, stats)
        self._persist_stats()

    def _maybe_enqueue_locked(self, template_id: str, stats: TemplateStats) -> None:
        if self._should_retire(template_id, stats):
            if self._store.retire(template_id):
                logger.info("[retrieval.growth] 退役低效模板 %s（avg=%.3f）", template_id, stats.avg_score)
            return
        if not self._should_author(template_id, stats):
            return
        if template_id in self._tasks:
            return
        self._tasks.append(template_id)
        if self._llm is not None:
            self._ensure_worker()
        self._wake.set()

    def _should_author(self, template_id: str, stats: TemplateStats) -> bool:
        if not self._cfg.authoring_enabled or self._llm is None:
            return False
        if stats.reports < self._cfg.min_samples:
            return False
        if stats.avg_score >= self._cfg.hit_threshold:
            return False
        now = time.time()
        if now - stats.last_authored_ts < self._cfg.cooldown_minutes * 60.0:
            return False
        if len(self._store.grown_templates()) >= self._cfg.max_templates:
            return False
        return True

    def _should_retire(self, template_id: str, stats: TemplateStats) -> bool:
        if self._store.get(template_id) is None:
            return False
        template = self._store.get(template_id)
        if template is None or template.source != "grown":
            return False
        return (
            stats.reports >= self._cfg.min_samples * 2
            and stats.avg_score < self._cfg.retire_threshold
        )

    # ── 后台造模板 ──────────────────────────────────────────────────────────

    def _ensure_worker(self) -> None:
        if self._lease is not None and self._lease.is_alive():
            return
        self._stop.clear()
        lease = get_thread_registry().request(
            "infra.retrieval.growth",
            f"template-author-{id(self):x}",
            self._run,
            daemon=True,
            stop=self._signal_stop,
        )
        lease.start()
        self._lease = lease

    def _signal_stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def stop(self, timeout: float = 30.0) -> None:
        self._signal_stop()
        if self._lease is not None:
            self._lease.stop(timeout=timeout)
            self._lease = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=_WAKE_POLL_SEC)
            self._wake.clear()
            with self._lock:
                pending, self._tasks = self._tasks, []
            for template_id in pending:
                if self._stop.is_set():
                    break
                try:
                    self._author_one(template_id)
                except Exception:
                    logger.warning(
                        "[retrieval.growth] 造模板失败 %s", template_id, exc_info=True
                    )

    def _author_one(self, template_id: str) -> None:
        with self._lock:
            template = self._store.get(template_id)
            examples = list(self._examples.get(template_id, []))
            stats = self._stats.get(template_id)
            if stats is not None:
                stats.last_authored_ts = time.time()
        if template is None or self._llm is None:
            return
        rendered = "\n".join(
            f"- {orig} → {query}（{'命中' if hit else 'NO_HITS'}）"
            for orig, query, hit in examples[-_MAX_LOW_EXAMPLES:]
        ) or "（无近期例子）"
        prompt = _AUTHOR_PROMPT.format(
            template_json=json.dumps(template.to_dict(), ensure_ascii=False),
            examples=rendered,
        )
        raw = self._llm.generate(prompt)
        new_template = self._parse_template(raw)
        if new_template is None:
            logger.info("[retrieval.growth] LLM 模板输出非法，已拒绝（%s）", template_id)
            return
        if self._store.add(new_template):
            logger.info(
                "[retrieval.growth] 新模板入库 %s（source=grown, 由 %s 派生）",
                new_template.template_id,
                template_id,
            )
        self._persist_stats()

    def _parse_template(self, raw: str) -> RewriteTemplate | None:
        text = str(raw or "").strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        try:
            payload = json.loads(text[start:end])
        except json.JSONDecodeError:
            return None
        patterns = [str(p) for p in (payload.get("patterns") or []) if str(p).strip()]
        if not patterns:
            return None
        has_capture = False
        for p in patterns:
            try:
                compiled = re.compile(p)
            except re.error:
                return None
            if compiled.groups >= 1:
                has_capture = True
        if not has_capture:
            return None  # 强制：必须含实体抽取捕获组
        name = str(payload.get("name") or "").strip()[:32] or "grown"
        frame = str(payload.get("frame") or "general")
        if frame not in ("general", "recall", "quote", "topic", "time", "verify"):
            frame = "general"
        template_id = f"grown.{int(time.time())}.{abs(hash(tuple(patterns))) % 9973}"
        return RewriteTemplate(
            template_id=template_id,
            name=name,
            source="grown",
            patterns=tuple(patterns),
            drop_words=frozenset(str(w) for w in (payload.get("drop_words") or [])),
            frame=frame,
        )

    # ── 统计持久化与观测 ─────────────────────────────────────────────────────

    def stats_for(self, template_id: str) -> dict[str, Any] | None:
        with self._lock:
            stats = self._stats.get(template_id)
            return stats.to_dict() if stats else None

    def status(self) -> dict[str, Any]:
        alive = self._lease is not None and self._lease.is_alive()
        with self._lock:
            queued = len(self._tasks)
            n_stats = len(self._stats)
        return {
            "enabled": self._cfg.enabled,
            "authoring": self._cfg.authoring_enabled and self._llm is not None,
            "state": "running" if alive else "idle",
            "queued": queued,
            "tracked": n_stats,
            "grown_templates": len(self._store.grown_templates()),
        }

    def _persist_stats(self) -> None:
        if not self._stats_path:
            return
        try:
            from pathlib import Path

            path = Path(self._stats_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = {tid: s.to_dict() for tid, s in self._stats.items()}
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except Exception:
            logger.debug("[retrieval.growth] stats persist failed", exc_info=True)

    def _load_stats(self) -> None:
        if not self._stats_path:
            return
        try:
            from pathlib import Path

            path = Path(self._stats_path)
            if not path.is_file():
                return
            payload = json.loads(path.read_text(encoding="utf-8"))
            for tid, row in (payload or {}).items():
                self._stats[str(tid)] = TemplateStats.from_dict(row)
        except Exception:
            logger.debug("[retrieval.growth] stats load failed", exc_info=True)
