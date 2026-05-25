from __future__ import annotations

from dataclasses import dataclass

from ...fsm.expectation import ExpectationState
from ...share_desire import (
    OUTBOUND_THRESHOLD_EAGER,
    OUTBOUND_THRESHOLD_MODERATE,
    ShareDesire,
    max_share_desire,
)
from ...transition.expectation import Expectation
from ...transition.interaction import PresenceInteraction
from .package import fold_share_queue
from .request import SpeakRequest


@dataclass
class SpeakInterfaceConfig:
    moderate_threshold: float = OUTBOUND_THRESHOLD_MODERATE
    eager_threshold: float = OUTBOUND_THRESHOLD_EAGER


class SpeakInterface:
    """egress 门控：冲动 + 分享队列 → SpeakRequest。"""

    def __init__(self, config: SpeakInterfaceConfig | None = None) -> None:
        self._config = config or SpeakInterfaceConfig()

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
        *,
        session_id: str,
        interaction: PresenceInteraction,
        expectation: ExpectationState,
    ) -> SpeakRequest | None:
        if interaction.impulse_level < self._config.moderate_threshold:
            return None
        package = fold_share_queue(expectation.share_queue, interaction)
        if not package.summary.strip():
            return None
        if interaction.expectation in (
            Expectation.required,
            Expectation.deferred,
            Expectation.clarify,
        ):
            return None
        share_desire = max_share_desire(
            max_share_desire(package.peak_share_desire, interaction.share_desire),
            self._share_desire_from_impulse(interaction.impulse_level),
        )
        return SpeakRequest(
            session_id=session_id,
            reason=package.summary,
            impulse_level=interaction.impulse_level,
            share_desire=share_desire,
            expectation=Expectation.required,
            package=package,
            source=interaction.impulse_source,
            wait_reply=True,
        )
