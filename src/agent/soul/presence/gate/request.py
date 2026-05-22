from __future__ import annotations

from dataclasses import dataclass

from ..capture.share_buffer import ShareFoldedPackage
from ..expectation import Expectation
from ..share_desire import ShareDesire


@dataclass(frozen=True)
class PresenceOutboundRequest:
    """冲动突破限值后，Soul 向顶层发起的交互请求。"""

    session_id: str
    reason: str
    impulse_level: float
    share_desire: ShareDesire
    expectation: Expectation
    package: ShareFoldedPackage
    source: str = ""
    wait_reply: bool = True

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "reason": self.reason,
            "impulse_level": self.impulse_level,
            "share_desire": self.share_desire.value,
            "expectation": self.expectation.value,
            "source": self.source,
            "wait_reply": self.wait_reply,
            "package": self.package.to_dict(),
        }
