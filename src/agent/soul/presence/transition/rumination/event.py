from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.heartbeat.bridge import MemoryHeartbeatResult


@dataclass(frozen=True)
class RuminationSignal:
    """Memory 反刍结果 → transition 的输入载荷。"""

    session_id: str
    hint: str
    wandered_ids: list[str] = field(default_factory=list)
    ruminated_ids: list[str] = field(default_factory=list)
    emotion: str = ""
    intensity: float = 0.0
    tick_id: str = ""
    trigger: str = "memory_ruminate"

    @classmethod
    def from_heartbeat_result(
        cls,
        result: MemoryHeartbeatResult,
        *,
        session_id: str = "tao",
    ) -> RuminationSignal | None:
        hint = (result.signal.narrative_hint or "").strip()
        ruminated_ids = list(result.ruminated_ids)
        wandered_ids = list(result.wandered_ids)
        if not hint and not ruminated_ids:
            return None
        return cls(
            session_id=session_id,
            hint=hint,
            wandered_ids=wandered_ids,
            ruminated_ids=ruminated_ids,
            emotion=(result.signal.dominant_emotion or "").strip(),
            intensity=float(result.signal.intensity),
            tick_id=(result.tick_id or result.signal.tick_id or "").strip(),
        )
