from __future__ import annotations

import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# 坏配置只警告一次（按 key 缓存），避免每个轮询周期刷屏
_WARNED_KEYS: set[tuple[str, str, str]] = set()


def within_window(start_str: str, end_str: str, tz_name: str, *, now: dtime | None = None) -> bool:
    """时间窗判定（活跃时段 / 注入窗口共用）。

    - ``start <= end``：同日窗口（含两端）；
    - ``start > end``：跨零点窗口（如 22:00–06:00）；
    - start/end 为空：视为无窗口，恒 True；
    - 时区/时间字符串解析失败：按 key 只警告一次并返回 True——
      心跳是唤起线，坏配置不允许杀死线程。

    ``now`` 供测试注入本地时刻；缺省取 ``tz_name`` 时区的当前时间。
    """
    if not start_str or not end_str:
        return True
    try:
        tz = ZoneInfo(tz_name)
        start = dtime.fromisoformat(start_str)
        end_ = dtime.fromisoformat(end_str)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        key = (start_str, end_str, tz_name)
        if key not in _WARNED_KEYS:
            _WARNED_KEYS.add(key)
            logger.warning("[HeartbeatWindow] 窗口配置无法解析，按无窗口处理：%r", key)
        return True
    now_local = now if now is not None else datetime.now(tz).time()
    if start <= end_:
        return start <= now_local <= end_
    return now_local >= start or now_local <= end_
