from __future__ import annotations

from dataclasses import dataclass

from ..capture import CaptureResult
from ..capture.share_buffer import ShareBuffer, fold_share_buffer
from ..expectation import Expectation
from ..share_desire import (
    OUTBOUND_THRESHOLD_EAGER,
    OUTBOUND_THRESHOLD_MODERATE,
    ShareDesire,
)
from .request import PresenceOutboundRequest


@dataclass
class PresenceGateConfig:
    """软阈值门控：按分享意愿分层决定是否 outbound。"""

    moderate_threshold: float = OUTBOUND_THRESHOLD_MODERATE
    eager_threshold: float = OUTBOUND_THRESHOLD_EAGER


class PresenceGate:
    """限值门控：捕获结束后按 share_desire 软分层检查是否突破。"""

    def __init__(self, config: PresenceGateConfig | None = None) -> None:
        self._config = config or PresenceGateConfig()

    @property
    def moderate_threshold(self) -> float:
        return self._config.moderate_threshold

    @property
    def eager_threshold(self) -> float:
        return self._config.eager_threshold

    def _share_desire_from_impulse(self, impulse_level: float) -> ShareDesire:
        if impulse_level >= self._config.eager_threshold:
            return ShareDesire.eager
        if impulse_level >= self._config.moderate_threshold:
            return ShareDesire.moderate
        return ShareDesire.mild

    def evaluate(
        self,
        result: CaptureResult,
        buffer: ShareBuffer | None = None,
    ) -> PresenceOutboundRequest | None:
        state = result.after
        behavior = state.behavior
        motivation = state.motivation
        if behavior.impulse_level < self._config.moderate_threshold:
            return None
        share_buffer = buffer or ShareBuffer()
        package = fold_share_buffer(share_buffer.entries, state)
        if not package.summary.strip():
            return None
        if behavior.expectation in (
            Expectation.required,
            Expectation.deferred,
            Expectation.clarify,
        ):
            return None
        share_desire = max(
            package.peak_share_desire,
            motivation.share_desire,
            self._share_desire_from_impulse(behavior.impulse_level),
        )
        return PresenceOutboundRequest(
            session_id=result.session_id,
            reason=package.summary,
            impulse_level=behavior.impulse_level,
            share_desire=share_desire,
            expectation=Expectation.required,
            package=package,
            source=behavior.impulse_source,
            wait_reply=True,
        )
