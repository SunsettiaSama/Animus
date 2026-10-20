from __future__ import annotations

from datetime import datetime, timedelta, timezone


def compute_landmark_trigger_at(
    now: datetime,
    *,
    gap_rounds: int,
    round_sec: float,
) -> datetime:
    """按触发轮次网格计算地标 ``scheduled_at``。"""
    if gap_rounds < 1:
        raise ValueError(f"gap_rounds 必须 >= 1，当前：{gap_rounds}")
    if round_sec <= 0:
        raise ValueError(f"round_sec 必须 > 0，当前：{round_sec}")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    epoch = now.timestamp()
    next_slot = (int(epoch // round_sec) + 1) * round_sec
    trigger_ts = next_slot + (gap_rounds - 1) * round_sec
    return datetime.fromtimestamp(trigger_ts, tz=timezone.utc)


def landmark_window_start(
    now: datetime | None = None,
    *,
    window_hours: float,
) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - timedelta(hours=window_hours)
