from __future__ import annotations

from dataclasses import dataclass

from ...transition.expectation import Expectation
from ...share_desire import ShareDesire
from .package import ShareFoldedPackage


@dataclass(frozen=True)
class SpeakRequest:
    """egress 出站：向 speak 层发起的主动说话请求。"""

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
