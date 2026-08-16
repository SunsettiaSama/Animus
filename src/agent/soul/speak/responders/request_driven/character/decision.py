from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from agent.soul.speak.responders.request_driven.directors.base import (
    DirectorLLMCaller,
    extract_json_object,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.speak_agenda import (
    BOOKING_GAP_MIN_SEC,
    CharacterSpeakAgenda,
)

HotAction = Literal["silence", "delay", "speak"]

_HOT_SYSTEM = (
    "你是角色本人。对方刚发来文字，这一拍要立刻决定怎么回应。"
    "三个选择：silence（本轮沉默，不写台词）、"
    "delay（本轮不写台词，稍后再开口）、"
    "speak（立刻回复）。"
    "先写清楚：你在做什么、心情如何、选哪个。"
    "选 delay 时写 at_sec（距现在多少秒后开口；系统硬间隔约 25 秒只是下限）。"
    "可以根据角色性格决定开口节奏——外向的角色可以更倾向 speak 或 short delay，内向或寡言的角色可以更倾向 silence 或 longer delay。"
    "不要写台词。输出 JSON："
    '{"doing":"…","mood":"…","action":"silence|delay|speak",'
    '"reason":"一两句理由","flush_body":"短动作","at_sec":40}'
)


@dataclass(frozen=True)
class HotTurnDecision:
    doing: str = ""
    mood: str = ""
    action: HotAction = "speak"
    reason: str = ""
    flush_body: str = ""
    at_sec: float = 0.0
    raw: str = ""

    @property
    def will_speak(self) -> bool:
        return self.action == "speak"

    @property
    def flush_text(self) -> str:
        if self.action == "speak":
            speak_flag = "要开口"
        elif self.action == "delay":
            speak_flag = "稍后开口"
        else:
            speak_flag = "先不开口"
        return (
            f"<speak>（{speak_flag}：{self.reason.strip() or '先按自己的节奏来。'}）</speak>"
        )


def _normalize_hot_action(raw: Any) -> HotAction:
    text = str(raw or "").strip().lower()
    if text in ("silence", "silent", "hold", "沉默", "不开口"):
        return "silence"
    if text in ("delay", "later", "book", "延迟", "稍后", "预约"):
        return "delay"
    if text in ("speak", "reply", "true", "1", "yes", "开口", "回复"):
        return "speak"
    if isinstance(raw, bool):
        return "speak" if raw else "silence"
    return "speak"


def decide_hot_turn(
    llm: DirectorLLMCaller | Any,
    *,
    session_id: str,
    turn_index: int = 0,
    user_text: str = "",
    plot_intent: str = "",
    rhythm_enrichment: str = "",
    interaction_record: str = "",
) -> HotTurnDecision:
    """用户热路径专用：沉默、延迟预约或立刻回复。不与 booked 共用。"""
    lines = [
        f"turn_index={turn_index}",
        "本拍是用户热入站。",
    ]
    if user_text.strip():
        lines.append(f"对方刚说：{user_text.strip()[:400]}")
    else:
        lines.append("对方这拍没有新话。")
    if plot_intent.strip():
        lines.append(f"本拍剧情：{plot_intent.strip()[:200]}")
    if rhythm_enrichment.strip():
        lines.append("导演用「你」给你的扩充：")
        lines.append(rhythm_enrichment.strip()[:600])
    if interaction_record.strip():
        lines.append("往来账本：")
        lines.append(interaction_record.strip()[:800])
    raw = ""
    if llm is not None and getattr(llm, "available", True):
        raw = str(
            llm.generate_json(
                system=_HOT_SYSTEM,
                user="\n".join(lines),
                session_id=session_id,
                director="character_hot_decision",
                turn_index=turn_index,
            )
            or ""
        )
    payload = extract_json_object(raw) if raw else {}
    if not payload:
        will = bool(user_text.strip())
        return HotTurnDecision(
            doing=plot_intent[:120],
            mood="",
            action="speak" if will else "silence",
            reason="对方在等你" if will else "你先把手头事做完",
            flush_body="你抬眼看了看通信设备" if will else "你继续做手头的事",
            at_sec=0.0,
            raw=raw,
        )
    action = _normalize_hot_action(payload.get("action", payload.get("will_speak")))
    at_sec = max(0.0, float(payload.get("at_sec") or 0.0))
    if action == "delay" and at_sec <= 0:
        at_sec = BOOKING_GAP_MIN_SEC
    return HotTurnDecision(
        doing=str(payload.get("doing") or "").strip()[:160],
        mood=str(payload.get("mood") or "").strip()[:120],
        action=action,
        reason=str(payload.get("reason") or "").strip()[:200],
        flush_body=str(payload.get("flush_body") or "").strip()[:160],
        at_sec=at_sec,
        raw=raw,
    )


def write_hot_delay_booking(
    state: Any,
    decision: HotTurnDecision,
    *,
    plot_unit_id: str = "",
    now: float | None = None,
) -> str:
    """热路径 delay：立刻写入一条 speak 预约，不经过后台轮询。"""
    if decision.action != "delay":
        return ""
    agenda = getattr(state, "speak_agenda", None)
    if agenda is None:
        agenda = CharacterSpeakAgenda()
        state.speak_agenda = agenda
    current = time.time() if now is None else float(now)
    at_sec = decision.at_sec if decision.at_sec > 0 else BOOKING_GAP_MIN_SEC
    entry = agenda.add_speak(
        at=current + at_sec,
        source="character",
        plot_unit_id=str(plot_unit_id or "").strip(),
        reason=decision.reason.strip() or "热路径延迟开口",
        duration_sec=at_sec,
        enforce=True,
    )
    cache = getattr(state, "director_cache", None)
    if isinstance(cache, dict):
        cache["speak_agenda"] = agenda.snapshot()
    notes = getattr(state, "notes", None)
    note = f"hot_delay_book:{entry.entry_id}@{entry.at:.0f}"
    if isinstance(notes, list):
        notes.append(note)
    return note


# 兼容旧测试名：TurnDecision 指向热路径决策
TurnDecision = HotTurnDecision