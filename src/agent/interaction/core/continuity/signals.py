from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from ..expectation import Expectation
from ..semantic import SemanticInteraction
from .types import ContinuityInput


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now(data: ContinuityInput) -> datetime:
    if data.now_iso:
        return _parse_iso(data.now_iso)
    return datetime.now(timezone.utc)


# 高置信「换题 / 新意图」
_BREAK_PHRASES = (
    r"换个话题",
    r"另外(问|说|聊)",
    r"顺便问",
    r"新问题",
    r"不说这个",
    r"先不管",
    r"重来",
    r"重新来",
    r"\bnew topic\b",
    r"\bchange topic\b",
)

# 高置信「仍在同一线」
_CONTINUE_PHRASES = (
    r"继续",
    r"接着说",
    r"然后呢",
    r"还有呢",
    r"展开",
    r"详细点",
    r"第三点",
    r"上面",
    r"刚才",
    r"这个",
    r"那个",
    r"它",
)

_BACKCHANNEL = frozenset({
    "嗯", "好", "好的", "行", "可以", "对", "是的", "ok", "okay", "yes", "y",
})


@dataclass(frozen=True)
class ContinuitySignals:
    has_active: bool
    active_open: bool
    idle_seconds: float
    incoming_len: int
    incoming_stripped: str
    expectation: Expectation | None
    last_agent_had_question: bool
    break_phrase_hit: bool
    continue_phrase_hit: bool
    is_backchannel: bool
    agent_still_deferred: bool


def build_signals(data: ContinuityInput) -> ContinuitySignals:
    active = data.active
    text = (data.incoming_user_text or "").strip()
    now = _now(data)

    idle_seconds = 0.0
    expectation = None
    last_agent_had_question = False
    if active is not None:
        expectation = active.expectation
        touch = active.last_touch_at or active.opened_at
        idle_seconds = max(0.0, (now - _parse_iso(touch)).total_seconds())
        if active.agent_utterances:
            last = active.agent_utterances[-1].text.strip()
            last_agent_had_question = "?" in last or "？" in last

    break_hit = any(re.search(p, text, re.I) for p in _BREAK_PHRASES)
    continue_hit = any(re.search(p, text, re.I) for p in _CONTINUE_PHRASES)
    is_backchannel = text.lower() in _BACKCHANNEL or (
        len(text) <= 4 and continue_hit
    )

    return ContinuitySignals(
        has_active=active is not None,
        active_open=active is not None and active.is_open,
        idle_seconds=idle_seconds,
        incoming_len=len(text),
        incoming_stripped=text,
        expectation=expectation,
        last_agent_had_question=last_agent_had_question,
        break_phrase_hit=break_hit,
        continue_phrase_hit=continue_hit,
        is_backchannel=is_backchannel,
        agent_still_deferred=expectation == Expectation.deferred,
    )
