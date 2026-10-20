"""speak 部位探针：speaking / typing。

只读 SoulService.speak（SpeakService）的聚合口 ``any_busy`` / ``any_typing``，
零侵入 speak 内部编排。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.soul.heartbeat.probe.base import SoulProbe

if TYPE_CHECKING:
    from agent.soul.service import SoulService


class SpeakProbe(SoulProbe):
    name = "speak"

    def __init__(self, soul: "SoulService | None") -> None:
        self._soul = soul

    def _sample(self) -> dict[str, Any]:
        speak = getattr(self._soul, "speak", None) if self._soul is not None else None
        if speak is None:
            raise RuntimeError("speak 未接线")
        return {
            "speaking": bool(speak.any_busy()),
            "typing": bool(speak.any_typing()),
        }
