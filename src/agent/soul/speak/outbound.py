from __future__ import annotations

from dataclasses import dataclass

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.state.dynamic.expectation.package import ShareFoldedPackage
from agent.soul.presence.transition.expectation import Expectation


@dataclass(frozen=True)
class SpeakRequest:
    """Speak 层出站：由 SoulService 在读完 presence 状态后构造。"""

    session_id: str
    reason: str
    impulse_level: float
    share_desire: ShareDesire
    expectation: Expectation
    package: ShareFoldedPackage
    source: str = ""
    wait_reply: bool = True
    presence_narrative: str = ""

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
            "presence_narrative": self.presence_narrative,
        }
