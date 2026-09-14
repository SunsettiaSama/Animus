"""memory/timeline.py — 时间轴读模型：append-only 对话轮流水（JSONL）。

背景（docs/product/single-stream-dialogue-requirements.md R2 / 开放问题 13）：
experience hub 为内存态，``close_dialogue`` 才交出记忆单元，无法直接按时间查询；
timeline v1 以 ``record_dialogue_turn`` 附带的轮次流水为读模型，记忆单元级时间轴
（语义层）后续另立。

- 写：``TurnJournal.append_turn``——线程安全、逐行 JSONL、按 channel 分文件；
  写失败只告警，绝不打断对话记账；
- 读：``read_timeline``——新条目在前分页（``before`` 游标为条目 ``at`` ISO 串）。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from config.storage import StorageConfig

_PAGE_LIMIT_DEFAULT = 50
_PAGE_LIMIT_MAX = 200


def _safe_channel(channel: str) -> str:
    return (
        str(channel or "main")
        .strip()
        .replace(":", "_")
        .replace("/", "_")
        .replace("\\", "_")
    ) or "main"


def channel_of(session_id: str) -> str:
    """session 形如 ``live:<channel>``；无前缀时 channel 即 session 本身。"""
    sid = str(session_id or "").strip()
    if sid.startswith("live:"):
        return sid[len("live:"):] or "main"
    return sid or "main"


class TurnJournal:
    """对话轮流水：每 channel 一个 JSONL 文件，append-only。"""

    def __init__(self, root_dir: str | None = None) -> None:
        self._root = root_dir or os.path.join(
            StorageConfig().timeline_dir, "dialogue"
        )
        self._lock = threading.Lock()

    def _path(self, channel: str) -> str:
        return os.path.join(self._root, f"{_safe_channel(channel)}.jsonl")

    def append_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        agent_text: str,
        salience: float = 0.3,
        emotion_label: str = "",
        proactive_intent_id: str = "",
    ) -> str | None:
        entry = {
            "id": uuid4().hex,
            "at": datetime.now(timezone.utc).isoformat(),
            "session_id": str(session_id or ""),
            "channel": channel_of(session_id),
            "user_text": str(user_text or ""),
            "agent_text": str(agent_text or ""),
            "salience": float(salience),
            "emotion_label": str(emotion_label or ""),
            "proactive_intent_id": str(proactive_intent_id or ""),
        }
        try:
            with self._lock:
                os.makedirs(self._root, exist_ok=True)
                with open(self._path(entry["channel"]), "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry["id"]
        except OSError:
            # 流水是读模型不是账本：写失败降级为丢条，不打断对话主路径
            return None

    def read(self, channel: str, *, limit: int, before: str = "") -> list[dict[str, Any]]:
        path = self._path(channel)
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        entries: list[dict[str, Any]] = []
        for line in reversed(lines):  # 新在前
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if before:
            entries = [e for e in entries if str(e.get("at", "")) < before]
        return entries[: max(1, min(limit, _PAGE_LIMIT_MAX))]


_journal: TurnJournal | None = None
_journal_lock = threading.Lock()


def default_journal() -> TurnJournal:
    global _journal
    with _journal_lock:
        if _journal is None:
            _journal = TurnJournal()
        return _journal


def read_timeline(
    *,
    channel: str,
    limit: int = _PAGE_LIMIT_DEFAULT,
    before: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """返回 (entries 新在前, next_before 游标)；游标为空表示没有更早内容。"""
    entries = default_journal().read(channel, limit=limit, before=before)
    next_before = ""
    if len(entries) >= max(1, min(limit, _PAGE_LIMIT_MAX)):
        next_before = str(entries[-1].get("at", ""))
    return entries, next_before
