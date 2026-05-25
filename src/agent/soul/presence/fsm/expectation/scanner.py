from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD, REPLY_URGE_THRESHOLD

from .package import fold_share_queue
from .queue import ShareIntentQueue
from .state import ExpectationState

if TYPE_CHECKING:
    from agent.soul.presence.interface.egress.request import SpeakRequest
    from agent.soul.presence.transition.interaction import PresenceInteraction


class ExpectationScanMode(str, Enum):
    none = "none"
    proactive_open = "proactive_open"
    append_message = "append_message"


@dataclass
class ExpectationScanResult:
    session_id: str
    triggered: bool = False
    mode: ExpectationScanMode = ExpectationScanMode.none
    speak_request: SpeakRequest | None = None
    notes: list[str] = field(default_factory=list)


_BLOCKED_PROACTIVE_VALUES = frozenset({"required", "deferred", "clarify"})


def _package_from_queue(
    queue: ShareIntentQueue,
    interaction: PresenceInteraction,
    summary: str,
):
    return fold_share_queue(queue, interaction, fallback_summary=summary)


def scan_expectation_thresholds(
    *,
    session_id: str,
    expectation: ExpectationState,
    interaction: PresenceInteraction,
    line_open: bool,
    proactive_threshold: float = PROACTIVE_OPEN_THRESHOLD,
    reply_threshold: float = REPLY_URGE_THRESHOLD,
) -> ExpectationScanResult:
    """扫描 FSM 期待驱动：超阈值则生成 proactive 开聊或对话内追加。"""
    from agent.soul.presence.interface.egress.request import SpeakRequest
    from agent.soul.presence.transition.expectation import Expectation
    from agent.soul.presence.share_desire import ShareDesire, share_desire_weight

    summary = expectation.share_queue.fold_summary() or expectation.reason.strip()
    if not summary:
        return ExpectationScanResult(session_id=session_id)

    if line_open and expectation.wants_multi_reply(threshold=reply_threshold):
        package = _package_from_queue(expectation.share_queue, interaction, summary)
        share_desire = package.peak_share_desire or ShareDesire.mild
        request = SpeakRequest(
            session_id=session_id,
            reason=summary,
            impulse_level=expectation.reply_urge,
            share_desire=share_desire,
            expectation=Expectation.optional,
            package=package,
            source="expectation_scan:append",
            wait_reply=False,
        )
        return ExpectationScanResult(
            session_id=session_id,
            triggered=True,
            mode=ExpectationScanMode.append_message,
            speak_request=request,
            notes=["reply_urge threshold → append message"],
        )

    if interaction.expectation.value in _BLOCKED_PROACTIVE_VALUES:
        return ExpectationScanResult(
            session_id=session_id,
            notes=["proactive blocked by interaction expectation"],
        )

    if expectation.at_proactive_threshold(threshold=proactive_threshold):
        package = _package_from_queue(expectation.share_queue, interaction, summary)
        share_desire = package.peak_share_desire or ShareDesire.mild
        if share_desire == ShareDesire.none:
            share_desire = ShareDesire.mild
        request = SpeakRequest(
            session_id=session_id,
            reason=summary,
            impulse_level=max(expectation.toward_user, share_desire_weight(share_desire)),
            share_desire=share_desire,
            expectation=Expectation.required,
            package=package,
            source="expectation_scan:proactive_open",
            wait_reply=True,
        )
        return ExpectationScanResult(
            session_id=session_id,
            triggered=True,
            mode=ExpectationScanMode.proactive_open,
            speak_request=request,
            notes=["toward_user threshold → proactive open"],
        )

    return ExpectationScanResult(session_id=session_id)
