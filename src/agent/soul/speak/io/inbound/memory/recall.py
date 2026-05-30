from __future__ import annotations

from dataclasses import dataclass

from .gateway import InboundMemoryGateway
from .request import RecallRequest


@dataclass
class RecallHandoffResult:
    ok: bool
    pointer: str = ""
    reason: str = ""
    query: str = ""
    full_text: str = ""
    trigger_source: str = "state:recall"


def render_recall_full_text(*, query: str, text: str) -> str:
    lines = [
        "【回忆检索】",
        f"检索词：{query.strip()}",
        "",
        text.strip() or "（未检索到相关记忆）",
    ]
    return "\n".join(lines)


def perform_recall_handoff(
    gateway: InboundMemoryGateway,
    *,
    session_id: str,
    query: str,
    top_k: int | None = None,
) -> RecallHandoffResult:
    normalized = query.strip()
    if not normalized:
        return RecallHandoffResult(
            ok=False,
            pointer="recall",
            reason="empty recall query",
        )

    result = gateway.recall(
        RecallRequest(session_id=session_id, query=normalized, top_k=top_k),
    )
    if not result.ok:
        return RecallHandoffResult(
            ok=False,
            pointer="recall",
            reason=result.reason or "recall failed",
            query=normalized,
        )

    return RecallHandoffResult(
        ok=True,
        pointer="recall",
        query=normalized,
        full_text=render_recall_full_text(query=normalized, text=result.text),
        trigger_source="state:recall",
    )
