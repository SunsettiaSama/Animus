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
    """对话轮流水：按 channel 分文件、按条数分段（每段默认 1000 条）。

    段文件命名 ``<channel>.<序号>.jsonl``（序号零填 4 位）；写满滚动新段。
    兼容旧版单文件 ``<channel>.jsonl``（作为最老段参与读取，不再写入）。
    前端 timeline API 与 speak 注入统一读本读模型——web 与本地文件天然对齐。
    """

    SEGMENT_MAX_ENTRIES = 1000

    def __init__(self, root_dir: str | None = None, *, segment_max: int | None = None) -> None:
        self._root = root_dir or os.path.join(
            StorageConfig().timeline_dir, "dialogue"
        )
        self._lock = threading.Lock()
        self._seg_max = max(1, int(segment_max or self.SEGMENT_MAX_ENTRIES))
        self._seg_counts: dict[str, int] = {}   # 活跃段路径 → 已写条数

    def _legacy_path(self, channel: str) -> str:
        return os.path.join(self._root, f"{_safe_channel(channel)}.jsonl")

    def _segment_path(self, channel: str, seq: int) -> str:
        return os.path.join(
            self._root, f"{_safe_channel(channel)}.{seq:04d}.jsonl"
        )

    def _paths(self, channel: str) -> list[str]:
        """全部段路径，旧 → 新（旧版单文件在最前，且不重复收集）。"""
        base = _safe_channel(channel)
        legacy_name = f"{base}.jsonl"
        legacy = os.path.join(self._root, legacy_name)
        segs = []
        try:
            for name in os.listdir(self._root):
                if name == legacy_name:
                    continue
                if name.startswith(f"{base}.") and name.endswith(".jsonl"):
                    segs.append(os.path.join(self._root, name))
        except OSError:
            pass
        segs.sort()
        out = []
        if os.path.isfile(legacy):
            out.append(legacy)
        out.extend(segs)
        return out

    def _active_segment(self, channel: str) -> tuple[str, int]:
        """活跃段（路径, 已写条数）：不存在或已满则滚动新段。"""
        paths = [p for p in self._paths(channel) if not p.endswith(
            f"{_safe_channel(channel)}.jsonl"
        )]
        if paths:
            active = paths[-1]
            count = self._seg_counts.get(active)
            if count is None:
                count = self._count_lines(active)
                self._seg_counts[active] = count
            if count < self._seg_max:
                return active, count
        seq = 1
        if paths:
            try:
                seq = int(paths[-1].rsplit(".", 2)[-2]) + 1
            except (IndexError, ValueError):
                seq = len(paths) + 1
        fresh = self._segment_path(channel, seq)
        self._seg_counts[fresh] = 0
        return fresh, 0

    @staticmethod
    def _count_lines(path: str) -> int:
        try:
            with open(path, "rb") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0

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
            "kind": "turn",
            "at": datetime.now(timezone.utc).isoformat(),
            "session_id": str(session_id or ""),
            "channel": channel_of(session_id),
            "user_text": str(user_text or ""),
            "agent_text": str(agent_text or ""),
            "salience": float(salience),
            "emotion_label": str(emotion_label or ""),
            "proactive_intent_id": str(proactive_intent_id or ""),
        }
        return self._append(entry)

    def append_event(
        self,
        *,
        session_id: str,
        text: str,
        kind: str = "story",
        beat_id: str = "",
        card_id: str = "",
        landmark_id: str = "",
        occurred_at: str = "",
        salience: float = 0.6,
    ) -> str | None:
        """生活/剧情事件条目（R5 provenance 落流水）：beat 演出、landmark 演化等。

        ``occurred_at`` 为剧情时间（如地标预约时刻），``at`` 为落账时间；
        与轮次条目同文件同序，读模型无需分叉。
        """
        entry = {
            "id": uuid4().hex,
            "kind": str(kind or "story"),
            "at": datetime.now(timezone.utc).isoformat(),
            "session_id": str(session_id or ""),
            "channel": channel_of(session_id),
            "text": str(text or ""),
            "beat_id": str(beat_id or ""),
            "card_id": str(card_id or ""),
            "landmark_id": str(landmark_id or ""),
            "occurred_at": str(occurred_at or ""),
            "salience": float(salience),
        }
        return self._append(entry)

    def _append(self, entry: dict[str, Any]) -> str | None:
        try:
            with self._lock:
                os.makedirs(self._root, exist_ok=True)
                active, count = self._active_segment(entry["channel"])
                with open(active, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                self._seg_counts[active] = count + 1
            return entry["id"]
        except OSError:
            # 流水是读模型不是账本：写失败降级为丢条，不打断对话主路径
            return None

    def read(self, channel: str, *, limit: int, before: str = "") -> list[dict[str, Any]]:
        paths = self._paths(channel)
        if not paths:
            return []
        lines: list[str] = []
        for path in paths:  # 段序旧 → 新；读模型 v1 整读（段有界，前段只减不增）
            try:
                with open(path, encoding="utf-8") as fh:
                    lines.extend(fh.readlines())
            except OSError:
                continue
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

    def recent_window(self, channel: str, k: int = 20) -> list[dict[str, Any]]:
        """时间轴窗口：最近 k 条（轮次/剧情事件混排），旧 → 新。

        上下文唯一历史语义（single-stream v7）：注入上下文只看时间轴
        最近 k 条，与会话/轮次机制无关。
        """
        entries = self.read(channel, limit=max(1, min(int(k), _PAGE_LIMIT_MAX)))
        entries.reverse()
        return entries


def _local_hhmm(raw: str) -> str:
    try:
        dt = datetime.fromisoformat(str(raw or "").strip())
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%H:%M")


def format_window_lines(
    entries: list[dict[str, Any]],
    *,
    cap: int = 200,
) -> list[str]:
    """时间轴条目 → 上下文行（与 page lines 同风格：用户：/角色：）。

    剧情事件带剧情时间戳（`[HH:MM] ◐ …`，本地时区）——注入的上下文
    与时间轴呈现同构：什么时间发生了什么事情。
    """
    lines: list[str] = []
    for entry in entries:
        kind = str((entry or {}).get("kind") or "turn")
        if kind == "story":
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            stamp = _local_hhmm(
                str(entry.get("occurred_at") or entry.get("at") or "")
            )
            lines.append(f"[{stamp}] ◐ {text[:cap]}" if stamp else f"◐ {text[:cap]}")
            continue
        user_text = str(entry.get("user_text") or "").strip()
        agent_text = str(entry.get("agent_text") or "").strip()
        if user_text:
            lines.append(f"用户：{user_text[:cap]}")
        if agent_text:
            lines.append(f"角色：{agent_text[:cap]}")
    return lines


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
