from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from react.persona.preference.entry import PreferenceEntry


class _Aggregated(NamedTuple):
    mood: str
    topic_interests: list[str]
    style_shifts: dict[str, float]
    entry_count: int
    latest_at: str


def _parse_dt(iso: str) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _fmt_date(iso: str) -> str:
    dt = _parse_dt(iso)
    return dt.strftime("%Y-%m-%d") if dt else iso[:10]


class RecentPreference:
    """近期偏好滑动窗口。

    维护最近 window_days 天内的 PreferenceEntry 列表，支持：
    - add()        追加新快照并自动剪枝
    - aggregate()  聚合窗口内所有条目，输出代表性偏好
    - render()     生成可注入 Prompt 的文本
    - to_query_bias()  返回用于偏置 L3 检索的关键词字符串
    """

    def __init__(
        self,
        entries: list[PreferenceEntry] | None = None,
        window_days: int = 7,
        max_topics: int = 5,
    ) -> None:
        self._entries: list[PreferenceEntry] = entries or []
        self._window_days = window_days
        self._max_topics = max_topics

    # ── 写入 ──────────────────────────────────────────────────────────────────

    def add(self, entry: PreferenceEntry) -> None:
        self._entries.append(entry)
        self._prune()

    def _prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._window_days)
        self._entries = [
            e for e in self._entries
            if (_parse_dt(e.recorded_at) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        ]

    # ── 聚合 ──────────────────────────────────────────────────────────────────

    def aggregate(self) -> _Aggregated:
        if not self._entries:
            return _Aggregated(
                mood="neutral",
                topic_interests=[],
                style_shifts={},
                entry_count=0,
                latest_at="",
            )

        sorted_entries = sorted(
            self._entries,
            key=lambda e: _parse_dt(e.recorded_at) or datetime.min.replace(tzinfo=timezone.utc),
        )
        latest = sorted_entries[-1]

        topic_counter: Counter[str] = Counter()
        shift_accum: dict[str, list[float]] = {}

        for e in sorted_entries:
            for t in e.topic_interests:
                topic_counter[t] += 1
            for k, v in e.style_shifts.items():
                shift_accum.setdefault(k, []).append(v)

        top_topics = [t for t, _ in topic_counter.most_common(self._max_topics)]
        avg_shifts = {k: round(sum(vs) / len(vs), 2) for k, vs in shift_accum.items()}

        return _Aggregated(
            mood=latest.mood,
            topic_interests=top_topics,
            style_shifts=avg_shifts,
            entry_count=len(sorted_entries),
            latest_at=latest.recorded_at,
        )

    # ── 输出 ──────────────────────────────────────────────────────────────────

    def render(self) -> str:
        agg = self.aggregate()
        if agg.entry_count == 0:
            return ""

        parts: list[str] = [
            f"（最近 {self._window_days} 天 · {agg.entry_count} 条记录）"
        ]
        if agg.mood and agg.mood != "neutral":
            parts.append(f"情绪倾向：{agg.mood}（更新于 {_fmt_date(agg.latest_at)}）")
        if agg.topic_interests:
            parts.append("话题兴趣：" + "、".join(agg.topic_interests))
        if agg.style_shifts:
            shift_strs = [
                f"{k}({v:+.2f})" for k, v in agg.style_shifts.items()
            ]
            parts.append("风格偏移：" + "、".join(shift_strs))

        return "\n".join(parts)

    def to_query_bias(self) -> str:
        agg = self.aggregate()
        return " ".join(agg.topic_interests)

    # ── 序列化 ────────────────────────────────────────────────────────────────

    @property
    def entries(self) -> list[PreferenceEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
