"""存活判定策略：状态变量 → 线体健康结论。

ok       线体健康
degraded 有失败记录或心跳自身读不到（仍在跑，需关注）
failing  连续失败达到阈值（唤起线带伤运行，应立即排查）

纯函数；阈值是策略常量，不进配置（避免又一个 yaml 面）。
"""

from __future__ import annotations

from agent.soul.heartbeat.vitals.snapshot import SoulVitals

FAILING_THRESHOLD = 3


def judge_liveness(vitals: SoulVitals | None) -> str:
    if vitals is None:
        return "degraded"  # 体征不可得本身就是需要关注的信号
    if vitals.heartbeat_failures >= FAILING_THRESHOLD:
        return "failing"
    if vitals.heartbeat_failures >= 1 or not vitals.thread_alive:
        return "degraded"
    if "heartbeat" in vitals.unknown_parts:
        return "degraded"
    return "ok"
