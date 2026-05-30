from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import config.soul.presence.config as presence_cfg

from agent.soul.presence.share_desire import ShareDesire, share_desire_weight
from agent.soul.presence.state.dynamic.kind import Expectation

from .package import ShareFoldedPackage, fold_share_queue
from .queue import ShareIntentQueue
from .state import ExpectationState

if TYPE_CHECKING:
    from agent.soul.presence.state.dynamic.interaction import PresenceInteraction


class ExpectationScanMode(str, Enum):
    none = "none"
    proactive_open = "proactive_open"
    append_message = "append_message"


@dataclass(frozen=True)
class ExpectationScanPayload:
    reason: str
    impulse_level: float
    share_desire: ShareDesire
    expectation: Expectation
    package: ShareFoldedPackage
    source: str
    wait_reply: bool


@dataclass
class ExpectationScanResult:
    session_id: str
    triggered: bool = False
    mode: ExpectationScanMode = ExpectationScanMode.none
    payload: ExpectationScanPayload | None = None
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
    proactive_threshold: float | None = None,
    reply_threshold: float | None = None,
) -> ExpectationScanResult:
    """扫描 FSM 期待驱动：超阈值则标记 proactive 开聊或对话内追加（不构造 speak 请求）。"""
    proactive = (
        presence_cfg.PROACTIVE_OPEN_THRESHOLD
        if proactive_threshold is None
        else proactive_threshold
    )
    reply = (
        presence_cfg.REPLY_URGE_THRESHOLD
        if reply_threshold is None
        else reply_threshold
    )
    summary = expectation.share_queue.fold_summary() or expectation.reason.strip()
    if not summary:
        return ExpectationScanResult(session_id=session_id)

    if line_open and expectation.wants_multi_reply(threshold=reply):
        package = _package_from_queue(expectation.share_queue, interaction, summary)
        share_desire = package.peak_share_desire or ShareDesire.mild
        payload = ExpectationScanPayload(
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
            payload=payload,
            notes=["reply_urge threshold → append message"],
        )

    if interaction.expectation.value in _BLOCKED_PROACTIVE_VALUES:
        return ExpectationScanResult(
            session_id=session_id,
            notes=["proactive blocked by interaction expectation"],
        )

    if expectation.at_proactive_threshold(threshold=proactive):
        package = _package_from_queue(expectation.share_queue, interaction, summary)
        share_desire = package.peak_share_desire or ShareDesire.mild
        if share_desire == ShareDesire.none:
            share_desire = ShareDesire.mild
        payload = ExpectationScanPayload(
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
            payload=payload,
            notes=["toward_user threshold → proactive open"],
        )

    return ExpectationScanResult(session_id=session_id)
