"""入睡避让策略：活跃时段边界不打断正在说话的 soul。

唤醒（wake）不受限——醒着说话永远合法；只有入睡让路。
纯函数、无副作用；``vitals=None`` 时放行。
"""

from __future__ import annotations

from agent.soul.heartbeat.vitals.snapshot import SoulVitals


def may_sleep(vitals: SoulVitals | None) -> tuple[bool, str]:
    """返回 (是否允许入睡, 避让原因)。"""
    if vitals is not None and vitals.speaking:
        return False, "soul speaking"
    return True, ""
