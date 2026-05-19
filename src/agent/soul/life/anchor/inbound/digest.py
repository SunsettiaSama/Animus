from __future__ import annotations

from ..chronicle import AnchorChronicleEntry, AnchorChronicleKind, AnchorChronicleStore


class SchedulerDigestRecorder:
    """Heartbeat 调度摘要 → Anchor Chronicle。"""

    def __init__(self, chronicle: AnchorChronicleStore) -> None:
        self._chronicle = chronicle

    def record(self, tasks_text: str) -> None:
        body = tasks_text.strip()
        if not body:
            return
        self._chronicle.append(AnchorChronicleEntry(
            kind=AnchorChronicleKind.scheduler_digest,
            summary=f"调度侧近期完成任务摘要：\n{body}"[:500],
        ))
