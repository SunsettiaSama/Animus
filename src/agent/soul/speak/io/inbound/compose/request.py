from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SpeakTurnMode = Literal["inbound", "proactive"]


@dataclass(frozen=True)
class ComposePrepareRequest:
    """inbound → compose：预组装请求。"""

    session_id: str
    mode: SpeakTurnMode = "inbound"
