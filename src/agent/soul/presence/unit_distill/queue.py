from __future__ import annotations

from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.life.experience.ingest.presence import hot_units_for_session
from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog


def select_distill_batch(
    log: ExperienceLog,
    session_id: str,
    *,
    batch_k: int,
    last_distilled_unit_id: str = "",
    hours: float | None = 48,
    tail: int = 24,
) -> list[ExperienceUnit]:
    """按 ingest 批次取最近 k 个 unit；跳过已蒸馏游标之前的重复。"""
    units = hot_units_for_session(log, session_id, hours=hours, tail=tail)
    if not units:
        return []
    if last_distilled_unit_id:
        ids = [u.id for u in units]
        if last_distilled_unit_id in ids:
            idx = ids.index(last_distilled_unit_id)
            units = units[idx + 1 :]
    if not units:
        return []
    k = max(1, batch_k)
    return units[-k:]
