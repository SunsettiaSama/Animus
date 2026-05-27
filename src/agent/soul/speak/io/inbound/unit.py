from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..outbound.unit import SpeakAnswer
from ...session import SpeakFeelingChunk, SpeakSubjectiveChunk


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass
class SpeakQuestion:
    """用户侧最小话语单元。"""

    text: str
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)


@dataclass
class SpeakExchange:
    """Soul 对话最小问答单元：一问一答绑定，不可再分。"""

    session_id: str
    question: SpeakQuestion
    answer: SpeakAnswer | None = None
    subjective: SpeakSubjectiveChunk = field(default_factory=SpeakSubjectiveChunk)
    feeling: SpeakFeelingChunk = field(default_factory=SpeakFeelingChunk)
    id: str = field(default_factory=_uid)
