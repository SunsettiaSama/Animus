from __future__ import annotations

from .event import LedgerEvent, LedgerEventKind
from .log import LedgerEventLog


def timeline_entries_recent(log: LedgerEventLog, days: int = 7) -> list[tuple[str, str]]:
    """近期账本条目 → ``(ts_iso, fact_line)``，供叙事侧按时间合并（叙事模块不引用 Ledger 类型）。"""
    return [(e.ts, e.to_fact_line()) for e in log.recent(days=days)]


def count_dialogue_recent(log: LedgerEventLog, days: int = 7) -> int:
    kinds = (LedgerEventKind.TAO_DIALOGUE, LedgerEventKind.INTERACTION)
    return len([e for e in log.recent(days=days) if e.kind in kinds])


def append_scheduler_digest(log: LedgerEventLog, tasks_text: str) -> LedgerEvent | None:
    body = tasks_text.strip()
    if not body:
        return None
    ev = LedgerEvent.now(
        LedgerEventKind.TASK,
        f"调度侧近期完成任务摘要：\n{body}",
        source="heartbeat_scheduler",
    )
    log.append(ev)
    return ev
