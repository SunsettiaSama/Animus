from __future__ import annotations

from dataclasses import dataclass

from .share_desire import ShareDesire
from .state.dynamic.expectation.package import ShareFoldedPackage
from .transition.expectation import Expectation


@dataclass(frozen=True)
class ImpulseDischarge:
    """累积冲动放电结果（只读快照，由上层决定是否 speak）。"""

    session_id: str
    reason: str
    impulse_level: float
    share_desire: ShareDesire
    expectation: Expectation
    package: ShareFoldedPackage
    source: str
    wait_reply: bool
