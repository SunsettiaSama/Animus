from __future__ import annotations

import time
from typing import Any

from agent.soul.speak.responders.request_driven.orchestrator.state.core.speak_agenda import (
    CharacterSpeakAgenda,
)


def _consume_active_pair(state: Any, *, reason: str) -> bool:
    """预约路径：同步消费当前剧情+节奏对（不经导演 LLM）。"""
    plot_arc = getattr(state, "plot_arc", None)
    if plot_arc is None or not getattr(plot_arc, "ready", False):
        return False
    active = plot_arc.active_unit() if hasattr(plot_arc, "active_unit") else None
    if active is None:
        return False
    unit_id = str(getattr(active, "unit_id", "") or "").strip()
    if not unit_id:
        return False
    rhythm = getattr(state, "character_rhythm_schedule", None)
    rhythm_unit = None
    if rhythm is not None and hasattr(rhythm, "unit_for_plot"):
        rhythm_unit = rhythm.unit_for_plot(unit_id)

    from agent.soul.speak.responders.request_driven.screenwriter import Screenwriter

    Screenwriter(llm=None).confirm_interaction_unit_complete(
        state,
        poll_seq=int(getattr(state, "poll_seq", 0) or 0),
        reason=reason,
        session_id=str(getattr(state, "session_id", "") or "").strip(),
        unit_id=unit_id,
    )
    if (
        rhythm is not None
        and rhythm_unit is not None
        and rhythm_unit.status in ("pending", "reserved")
    ):
        rhythm.mark_consumed(
            rhythm_unit.unit_id,
            trigger_id=reason,
            plot_fingerprint=unit_id,
        )
        cache = getattr(state, "director_cache", None)
        if isinstance(cache, dict):
            cache["character_rhythm_schedule"] = rhythm.snapshot()
    notes = getattr(state, "notes", None)
    if isinstance(notes, list):
        notes.append(f"pair_consume: {reason} plot={unit_id}")
    return True


def apply_bookings_to_agenda(
    agenda: CharacterSpeakAgenda,
    bookings: list[dict[str, Any]],
    *,
    now: float | None = None,
    default_plot_unit_id: str = "",
    state: Any = None,
) -> list[str]:
    """把角色预约写入议程；过硬间隔；撞导演戳则让路。

    热路径 delay / 后台 book_poll 各自直接 add_speak；本函数留给批量写入与测试。
    """
    current = time.time() if now is None else float(now)
    notes: list[str] = []
    active_plot = ""
    if state is not None:
        plot_arc = getattr(state, "plot_arc", None)
        if plot_arc is not None and getattr(plot_arc, "ready", False):
            active = plot_arc.active_unit() if hasattr(plot_arc, "active_unit") else None
            if active is not None:
                active_plot = str(getattr(active, "unit_id", "") or "").strip()
    for item in bookings:
        kind = str(item.get("kind") or "speak").strip().lower()
        reason = str(item.get("reason") or "").strip()
        plot_id = str(item.get("plot_unit_id") or default_plot_unit_id or "").strip()
        at = current + max(0.0, float(item.get("at_sec") or 0.0))
        duration_sec = max(0.0, float(item.get("duration_sec") or 0.0))
        if state is not None and plot_id and active_plot and plot_id != active_plot:
            if _consume_active_pair(state, reason="booking_next_plot"):
                notes.append(f"consume_pair_before_book:{plot_id}")
                active_plot = plot_id
        if kind == "silence":
            end_sec = item.get("end_sec")
            end = current + max(float(end_sec or 0.0), at - current + 25.0)
            if state is not None and active_plot:
                rhythm = getattr(state, "character_rhythm_schedule", None)
                unit = (
                    rhythm.unit_for_plot(active_plot)
                    if rhythm is not None and hasattr(rhythm, "unit_for_plot")
                    else None
                )
                window_end = getattr(unit, "window_end", None) if unit is not None else None
                if window_end is not None and float(end) >= float(window_end):
                    if _consume_active_pair(
                        state, reason="booking_silence_to_window_end"
                    ):
                        notes.append("consume_pair_silence_window")
                        active_plot = ""
            entry = agenda.add_silence(
                start=at,
                end=end,
                source="character",
                plot_unit_id=plot_id,
                reason=reason,
                duration_sec=duration_sec,
                enforce=True,
            )
            notes.append(f"book_silence:{entry.entry_id}@{entry.at:.0f}")
        else:
            entry = agenda.add_speak(
                at=at,
                source="character",
                plot_unit_id=plot_id,
                reason=reason,
                duration_sec=duration_sec,
                enforce=True,
            )
            notes.append(f"book_speak:{entry.entry_id}@{entry.at:.0f}")
    return notes
