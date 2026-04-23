from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from config.react.memory.medium_term_config import MediumTermMemoryConfig

if TYPE_CHECKING:
    from llm_core.llm import BaseLLM

_FILENAME       = "medium_term.jsonl"
_CACHE_FILENAME = "medium_term_consolidate.json"

# 写入即蒸馏：将单条 Q&A 压缩为知识摘要
_DISTILL_SINGLE_PROMPT = """\
You are a memory distiller for a conversational AI agent.
Summarize the following conversation turn into a concise memory note (≤{max_tokens} words).
Focus on: key facts the user shared, topics covered, decisions made, notable context.
Omit pleasantries, filler, and redundant detail.

Q: {question}
A: {answer}

Output only the memory note, no preamble."""

# 高阶归并：将多条摘要归并为一条更高阶的摘要
_CONSOLIDATE_PROMPT = """\
You are a memory consolidator for a conversational AI agent.
The following memory entries are the oldest in the agent's memory and will be replaced \
by a single merged summary. Write a concise, coherent narrative (≤{max_tokens} words) \
that preserves all key facts, decisions, and context.

Entries to merge:
{entries}

Output only the merged summary, no preamble."""


class RecentHistoryMemory:
    """近期对话记忆，写入时立即蒸馏，溢出时高阶归并。

    写入策略（distill_on_write=True）：
      每条 Q&A 写入时立即调用 LLM 蒸馏为知识摘要；LLM 不可用或蒸馏结果为空
      时降级存原文，确保条目不丢失。

    溢出策略（consolidate_enabled=True）：
      当摘要条数超出 max_entries 时，把最旧的 consolidate_batch 条归并为
      一条更高阶的摘要（summary-of-summaries），而非重新蒸馏原文。

    线程安全：
      _entries 由 _lock（RLock）保护。render() 和 append() 均在持锁状态下
      访问列表，避免 post_process 线程与下一轮 stream 线程并发读写。

    兼容性：
      旧格式（无 type 字段）的原文条目在加载后仍可正常渲染，
      新写入的条目一律为 type=summary。
    """

    def __init__(self, cfg: MediumTermMemoryConfig, llm: BaseLLM | None = None) -> None:
        self._cfg = cfg
        self._llm: BaseLLM | None = llm if (cfg.distill_on_write or cfg.consolidate_enabled) else None
        self._lock = threading.RLock()
        if cfg.memory_dir:
            self._path       = os.path.join(cfg.memory_dir, _FILENAME)
            self._cache_path = os.path.join(cfg.memory_dir, _CACHE_FILENAME)
        else:
            self._path = self._cache_path = ""
        self._entries: list[dict] = self._load() if self._path else []

    # ── public API ────────────────────────────────────────────────────────────

    def render(self) -> str:
        """将近期条目渲染为 prompt 文本；若无条目返回空串。"""
        with self._lock:
            entries = list(self._entries)
        parts = []
        for e in entries:
            date = e.get("ts", "")[:10]
            if e.get("type") == "summary":
                text = e.get("text", "").strip()
                if text:
                    parts.append(f"[{date}] {text}")
            else:
                q = e.get("q", "").strip()
                a = e.get("a", "").strip()
                if q and a:
                    parts.append(f"[{date}]\nQ: {q}\nA: {a}")
        text = "\n\n".join(parts)
        if self._cfg.max_chars > 0 and len(text) > self._cfg.max_chars:
            text = text[-self._cfg.max_chars:]
        return text

    def append(self, question: str, answer: str) -> None:
        """追加一条记录：有 LLM 且 distill_on_write=True 时立即蒸馏。

        蒸馏结果为空则降级存原文，确保条目不会因 LLM 异常而丢失。
        """
        if not self._path:
            return
        os.makedirs(os.path.dirname(self._path), exist_ok=True)

        entry = self._make_entry(question, answer)

        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._entries.append(entry)
            self._maybe_consolidate()

    def consolidate(self, force: bool = False) -> bool:
        """高阶归并：把最旧的 consolidate_batch 条摘要归并为一条更高阶的摘要。

        返回 True 表示实际执行了归并，False 表示条件不满足。
        """
        with self._lock:
            if not self._path or self._llm is None:
                return False
            if not force and not self._should_consolidate():
                return False
            batch_size = self._cfg.consolidate_batch
            if len(self._entries) <= batch_size:
                return False

            batch = self._entries[:batch_size]
            rest  = self._entries[batch_size:]

        lines = []
        for i, e in enumerate(batch, 1):
            if e.get("type") == "summary":
                lines.append(f"{i}. {e.get('text', '').strip()}")
            else:
                lines.append(f"{i}. Q: {e.get('q', '')}\n   A: {e.get('a', '')}")
        entries_text = "\n\n".join(lines)

        prompt = _CONSOLIDATE_PROMPT.format(
            max_tokens=self._cfg.max_consolidate_tokens,
            entries=entries_text,
        )
        summary_text = self._llm.generate(prompt)
        if not summary_text.strip():
            return False

        merged = {
            "type": "summary",
            "ts":           batch[-1].get("ts", ""),
            "period_start": batch[0].get("ts", ""),
            "period_end":   batch[-1].get("ts", ""),
            "text": summary_text,
        }
        with self._lock:
            self._entries = [merged] + rest
            self._rewrite()
            self._write_cache()
        return True

    @property
    def has_distillate(self) -> bool:
        with self._lock:
            return any(e.get("type") == "summary" for e in self._entries)

    @property
    def distillate(self) -> str:
        """返回最新一条摘要文本（供 MemoryProcessor.commit 引用）。"""
        with self._lock:
            for e in reversed(self._entries):
                if e.get("type") == "summary":
                    return e.get("text", "")
        return ""

    # ── internal ──────────────────────────────────────────────────────────────

    def _make_entry(self, question: str, answer: str) -> dict:
        """构造写入条目：有 LLM 且蒸馏结果非空时返回摘要，否则返回原文。"""
        if self._cfg.distill_on_write and self._llm is not None:
            summary_text = self._llm.generate(
                _DISTILL_SINGLE_PROMPT.format(
                    max_tokens=self._cfg.max_distill_tokens,
                    question=question,
                    answer=answer,
                )
            )
            if summary_text.strip():
                now = datetime.now(timezone.utc).isoformat()
                return {
                    "type": "summary",
                    "ts": now,
                    "period_start": now,
                    "period_end": now,
                    "text": summary_text,
                }
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "q": question,
            "a": answer,
        }

    def _load(self) -> list[dict]:
        if not os.path.exists(self._path):
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._cfg.window_days)
        entries: list[dict] = []
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                e = json.loads(raw)
                ts_str = e.get("ts", "")
                if not ts_str:
                    continue
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    entries.append(e)
        if self._cfg.max_entries > 0 and len(entries) > self._cfg.max_entries:
            entries = entries[-self._cfg.max_entries:]
        return entries

    def _should_consolidate(self) -> bool:
        if len(self._entries) <= self._cfg.consolidate_batch:
            return False
        interval = self._cfg.consolidate_interval_days
        if interval <= 0:
            return True
        last = self._read_cache_date()
        if last is None:
            return True
        return (datetime.now(timezone.utc).date() - last).days >= interval

    def _maybe_consolidate(self) -> None:
        if (
            self._llm is not None
            and self._cfg.consolidate_enabled
            and len(self._entries) > self._cfg.max_entries
        ):
            self.consolidate(force=False)

    def _rewrite(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            for e in self._entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # ── cache helpers ─────────────────────────────────────────────────────────

    def _read_cache_date(self):
        if not self._cache_path or not os.path.exists(self._cache_path):
            return None
        with open(self._cache_path, encoding="utf-8") as f:
            data = json.load(f)
        last_date = data.get("last_date", "")
        if not last_date:
            return None
        return datetime.fromisoformat(last_date).date()

    def _write_cache(self) -> None:
        if not self._cache_path:
            return
        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump({"last_date": datetime.now(timezone.utc).date().isoformat()}, f)
