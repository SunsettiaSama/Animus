"""注入避让策略：soul 正在说话时不注入（防串台）。

纯函数、无副作用；``vitals=None``（体征不可得）时放行——
部位缺失不阻断既有行为。
"""

from __future__ import annotations

from agent.soul.heartbeat.vitals.snapshot import SoulVitals


def should_offer_inject(vitals: SoulVitals | None) -> tuple[bool, str]:
    """返回 (是否放行, 避让原因)；不放行时文本留在 deferred 下轮重试。"""
    if vitals is not None and vitals.speaking:
        return False, "soul speaking"
    return True, ""
