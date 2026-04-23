from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from config.react.memory.medium_term_config import MediumTermMemoryConfig

if TYPE_CHECKING:
    from llm_core.llm import BaseLLM

_FILENAME       = "medium_term.jsonl"
_CACHE_FILENAME = "medium_term_consolidate.json"

_CONSOLIDATE_PROMPT = """\
You are a memory consolidator for a conversational AI agent.
The following Q&A pairs are the oldest entries in the agent's medium-term memory and \
will be replaced by this summary. Write a concise, coherent narrative (within \
{max_tokens} words) that preserves all key facts, decisions, and context so future \
conversations can reference them naturally.

Entries to consolidate:
{entries}

Output only the consolidated summary, no preamble."""


class RecentHistoryMemory:
    """近期对话历史记忆（最近 k 天），以追加写 JSONL 持久化。

    写入时机：post_process()（后台线程），用户看到输出后立即异步落盘，零感知延迟。
    读取时机：每轮 stream() 启动时从磁盘加载，自动包含所有已完成的历史。

    整合策略：
    - 自动整合：commit() 之后检查，若超出 max_entries 且距上次整合已满
      consolidate_interval_days 天，则把最旧的 consolidate_batch 条蒸馏为一条摘要。
    - 强制整合：consolidate(force=True)，供 WebUI「立即整理」按钮调用。

    Ctrl+C 等异常退出仅可能导致最后一行不完整，加载时会跳过无法解析的行。
    """

    def __init__(self, cfg: MediumTermMemoryConfig, llm: BaseLLM | None = None) -> None:
        self._cfg = cfg
        self._llm: BaseLLM | None = llm if cfg.consolidate_enabled else None
        if cfg.memory_dir:
            self._path       = os.path.join(cfg.memory_dir, _FILENAME)
            self._cache_path = os.path.join(cfg.memory_dir, _CACHE_FILENAME)
        else:
            self._path = self._cache_path = ""
        self._entries: list[dict] = self._load() if self._path else []

    # ── public API ────────────────────────────────────────────────────────────

    def render(self) -> str:
        """将近期条目渲染为 prompt 文本；若无条目返回空串。"""
        if not self._entries:
            return ""
        parts = []
        for e in self._entries:
            if e.get("type") == "summary":
                period = f"{e.get('period_start','')[:10]} ~ {e.get('period_end','')[:10]}"
                parts.append(f"[{period}] (summary)\n{e.get('text','').strip()}")
            else:
                date = e.get("ts", "")[:10]
                q = e.get("q", "").strip()
                a = e.get("a", "").strip()
                if q and a:
                    parts.append(f"[{date}]\nQ: {q}\nA: {a}")
        text = "\n\n".join(parts)
        if self._cfg.max_chars > 0 and len(text) > self._cfg.max_chars:
            text = text[-self._cfg.max_chars:]
        return text

    def append(self, question: str, answer: str) -> None:
        """追加一条 Q&A 记录，然后检查是否触发自动整合。"""
        if not self._path:
            return
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "q": question,
            "a": answer,
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._entries.append(entry)
        self._maybe_consolidate()

    def consolidate(self, force: bool = False) -> bool:
        """执行一次整合。force=True 跳过日期节流检查。
        返回 True 表示实际执行了整合，False 表示条件不满足。
        """
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
                lines.append(f"{i}. [Summary] {e.get('text','')}")
            else:
                lines.append(f"{i}. Q: {e.get('q','')}\n   A: {e.get('a','')}")
        entries_text = "\n\n".join(lines)

        prompt = _CONSOLIDATE_PROMPT.format(
            max_tokens=self._cfg.max_consolidate_tokens,
            entries=entries_text,
        )
        summary_text = self._llm.generate(prompt)

        summary_entry = {
            "type": "summary",
            "ts":           batch[-1].get("ts", ""),
            "period_start": batch[0].get("ts", ""),
            "period_end":   batch[-1].get("ts", ""),
            "text": summary_text,
        }
        self._entries = [summary_entry] + rest
        self._rewrite()
        self._write_cache()
        return True

    # ── internal ──────────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if not os.path.exists(self._path):
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._cfg.window_days)
        entries: list[dict] = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = e.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                # summary 条目：period_end 在窗口内即保留
                if ts >= cutoff:
                    entries.append(e)
        if self._cfg.max_entries > 0 and len(entries) > self._cfg.max_entries:
            entries = entries[-self._cfg.max_entries:]
        return entries

    def _should_consolidate(self) -> bool:
        """是否满足自动整合条件：超出 max_entries 且距上次满足 interval。"""
        if len(self._entries) <= self._cfg.consolidate_batch:
            return False
        interval = self._cfg.consolidate_interval_days
        if interval <= 0:
            return True
        last = self._read_cache_date()
        if last is None:
            return True
        return (datetime.now(timezone.utc).date() - last).days >= interval

    def _rewrite(self) -> None:
        """将内存中的 _entries 完整重写到 JSONL 文件。"""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            for e in self._entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def _maybe_consolidate(self) -> None:
        if (
            self._llm is not None
            and self._cfg.consolidate_enabled
            and len(self._entries) > self._cfg.max_entries
        ):
            self.consolidate(force=False)

    # ── cache helpers ─────────────────────────────────────────────────────────

    def _read_cache_date(self):
        if not self._cache_path or not os.path.exists(self._cache_path):
            return None
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
            return datetime.fromisoformat(data["last_date"]).date()
        except Exception:
            return None

    def _write_cache(self) -> None:
        if not self._cache_path:
            return
        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump({"last_date": datetime.now(timezone.utc).date().isoformat()}, f)
