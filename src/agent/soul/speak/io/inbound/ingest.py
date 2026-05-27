from __future__ import annotations

from dataclasses import dataclass, field

from .unit import SpeakExchange, SpeakQuestion


@dataclass
class SpeakIngestResult:
    """用户话语摄入结果。"""

    exchange: SpeakExchange
    notes: list[str] = field(default_factory=list)


def ingest_question(session_id: str, text: str) -> SpeakIngestResult:
    """入站：构造一问一答 exchange（尚未记账）。"""
    exchange = SpeakExchange(
        session_id=session_id,
        question=SpeakQuestion(text=text),
    )
    return SpeakIngestResult(exchange=exchange)
