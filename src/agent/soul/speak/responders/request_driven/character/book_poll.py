from __future__ import annotations

import logging
import time
from typing import Any

from agent.soul.speak.responders.request_driven.directors.base import (
    extract_json_object,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.speak_agenda import (
    BOOKING_GAP_MIN_SEC,
    CharacterSpeakAgenda,
)

logger = logging.getLogger(__name__)

# 角色后台预约轮询：独立常量，不调用导演 should_wake_narrative
INTERACTION_ROUNDS_BEFORE_BOOK_POLL = 3
MIN_TOTAL_UNITS_BEFORE_BOOK_POLL = 5

_BOOK_POLL_SYSTEM = (
    "你是角色本人，在后台决定要不要预约下一次开口。"
    "只需要说明是否预约。不写台词，不安排多条。"
    "不预约时不需要写 at_sec。"
    "预约时写 at_sec（距现在的秒数，系统硬间隔约 25 秒只是下限）和 reason。"
    "可以根据角色性格判断预约频率，话多的角色可以多约，话少的可以少约或不约。"
    "输出文风保持客观、冷静、朴实。不用修辞，不抒情，不说教。\n"
    "输出 JSON："
    '{"should_book":false,"at_sec":40,"reason":"…","plot_unit_id":""}'
)


def should_poll_character_book(state: Any) -> bool:
    """满足 K 轮往来，或 unit 总数比上次角色预约轮询时多出超过阈值。"""
    exchanges = int(getattr(state, "interaction_exchange_count", 0) or 0)
    polled_ex = int(getattr(state, "character_book_polled_at_exchange", 0) or 0)
    rounds_due = exchanges - polled_ex >= INTERACTION_ROUNDS_BEFORE_BOOK_POLL
    arc = getattr(state, "plot_arc", None)
    total = 0
    if arc is not None and getattr(arc, "ready", False):
        total = int(arc.total_unit_count())
    polled_total = int(getattr(state, "character_book_polled_at_total", 0) or 0)
    units_due = total - polled_total > MIN_TOTAL_UNITS_BEFORE_BOOK_POLL
    return rounds_due or units_due


def reset_character_book_poll(state: Any) -> None:
    """预约轮询落账后更新记录水位。"""
    state.character_book_polled_at_exchange = int(
        getattr(state, "interaction_exchange_count", 0) or 0
    )
    arc = getattr(state, "plot_arc", None)
    total = 0
    if arc is not None and getattr(arc, "ready", False):
        total = int(arc.total_unit_count())
    state.character_book_polled_at_total = total


def _active_plot_unit_id(state: Any) -> str:
    arc = getattr(state, "plot_arc", None)
    if arc is None or not getattr(arc, "ready", False):
        return ""
    active = arc.active_unit() if hasattr(arc, "active_unit") else None
    if active is None:
        return ""
    return str(getattr(active, "unit_id", "") or "").strip()


def _write_book_poll_speak(
    state: Any,
    *,
    at_sec: float,
    reason: str,
    plot_unit_id: str = "",
    now: float | None = None,
) -> str:
    """后台轮询自己写入一条 speak 预约，不经过热路径 delay。"""
    agenda = getattr(state, "speak_agenda", None)
    if agenda is None:
        agenda = CharacterSpeakAgenda()
        state.speak_agenda = agenda
    current = time.time() if now is None else float(now)
    delay = at_sec if at_sec > 0 else BOOKING_GAP_MIN_SEC
    entry = agenda.add_speak(
        at=current + delay,
        source="character",
        plot_unit_id=str(plot_unit_id or "").strip(),
        reason=reason.strip() or "后台预约开口",
        duration_sec=delay,
        enforce=True,
    )
    cache = getattr(state, "director_cache", None)
    if isinstance(cache, dict):
        cache["speak_agenda"] = agenda.snapshot()
    note = f"book_poll_speak:{entry.entry_id}@{entry.at:.0f}"
    notes = getattr(state, "notes", None)
    if isinstance(notes, list):
        notes.append(note)
    return note


def poll_character_book(
    llm: Any,
    state: Any,
    *,
    session_id: str,
    turn_index: int = 0,
    plot_intent: str = "",
    rhythm_enrichment: str = "",
    interaction_record: str = "",
) -> dict[str, Any]:
    """达到阈值后询问是否预约；否就跳过，是则写入一条预约。"""
    if not should_poll_character_book(state):
        return {"polled": False, "should_book": False, "reason": "threshold_not_met"}
    lines = [
        f"turn_index={turn_index}",
        "后台预约轮询：只需要判断要不要预约下一次开口。",
    ]
    if plot_intent.strip():
        lines.append(f"当前剧情：{plot_intent.strip()[:200]}")
    if rhythm_enrichment.strip():
        lines.append(rhythm_enrichment.strip()[:500])
    if interaction_record.strip():
        lines.append("往来账本：")
        lines.append(interaction_record.strip()[:800])
    raw = ""
    if llm is not None and getattr(llm, "available", True):
        raw = str(
            llm.generate_json(
                system=_BOOK_POLL_SYSTEM,
                user="\n".join(lines),
                session_id=session_id,
                director="character_book_poll",
                turn_index=turn_index,
            )
            or ""
        )
    payload = extract_json_object(raw) if raw else {}
    reset_character_book_poll(state)
    should_book = False
    if isinstance(payload, dict):
        flag = payload.get("should_book")
        if isinstance(flag, bool):
            should_book = flag
        else:
            should_book = str(flag or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "y",
                "是",
                "约",
            )
    if not should_book:
        notes = getattr(state, "notes", None)
        if isinstance(notes, list):
            notes.append("book_poll: skip_no_book")
        return {"polled": True, "should_book": False, "reason": "model_skip", "raw": raw}
    at_sec = max(0.0, float(payload.get("at_sec") or 0.0)) if isinstance(payload, dict) else 0.0
    reason = (
        str(payload.get("reason") or "").strip()[:240]
        if isinstance(payload, dict)
        else ""
    )
    plot_id = (
        str(payload.get("plot_unit_id") or "").strip()
        if isinstance(payload, dict)
        else ""
    ) or _active_plot_unit_id(state)
    note = _write_book_poll_speak(
        state,
        at_sec=at_sec,
        reason=reason or "后台决定预约开口",
        plot_unit_id=plot_id,
    )
    logger.info(
        "[character_book_poll] session=%s booked note=%s",
        session_id,
        note,
    )
    return {
        "polled": True,
        "should_book": True,
        "reason": reason,
        "note": note,
        "raw": raw,
    }


def maybe_poll_character_book(
    llm: Any,
    state: Any,
    *,
    session_id: str,
    turn_index: int = 0,
) -> dict[str, Any]:
    """poll_tick 挂点：未达到阈值则直接跳过。"""
    if not should_poll_character_book(state):
        return {"polled": False, "should_book": False, "reason": "threshold_not_met"}
    from agent.soul.speak.responders.request_driven.character.interaction import (
        export_interaction_record,
    )

    plot_intent = ""
    enrichment = ""
    plot_arc = getattr(state, "plot_arc", None)
    if plot_arc is not None and getattr(plot_arc, "ready", False):
        active = plot_arc.active_unit() if hasattr(plot_arc, "active_unit") else None
        if active is not None:
            plot_intent = str(getattr(active, "intent", "") or "").strip()
    rhythm = getattr(state, "character_rhythm_schedule", None)
    if rhythm is not None and plot_intent:
        unit = None
        active_id = _active_plot_unit_id(state)
        if active_id and hasattr(rhythm, "unit_for_plot"):
            unit = rhythm.unit_for_plot(active_id)
        if unit is not None and hasattr(unit, "render_script_for_character"):
            enrichment = str(unit.render_script_for_character() or "").strip()
    interaction = export_interaction_record(state).render_for_character()
    return poll_character_book(
        llm,
        state,
        session_id=session_id,
        turn_index=turn_index,
        plot_intent=plot_intent,
        rhythm_enrichment=enrichment,
        interaction_record=interaction,
    )