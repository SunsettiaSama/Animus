from __future__ import annotations

import time
from typing import Any

# Speak 独立服务：超过此时长无交互 → 进入静默；下次接入再初始化叙事
SPEAK_IDLE_DORMANT_SEC = 1800.0


def last_interaction_at(state: Any) -> float:
    """最近一次可计为「交互」的时间戳。

    优先用户/角色可见开口；尚无开口时才回落到叙事初始化时间。
    编剧 poll 续写不刷新交互时钟，避免空转永远进不了静默。
    """
    user = float(getattr(state, "last_user_speak_at", 0.0) or 0.0)
    agent = float(getattr(state, "last_agent_speak_at", 0.0) or 0.0)
    speak_stamp = max(user, agent)
    if speak_stamp > 0:
        return speak_stamp
    stamps = []
    plot = getattr(state, "plot_flow", None)
    if plot is not None:
        stamps.append(float(getattr(plot, "revised_at", 0.0) or 0.0))
    arc = getattr(state, "plot_arc", None)
    if arc is not None:
        stamps.append(float(getattr(arc, "initialized_at", 0.0) or 0.0))
    presence = getattr(state, "presence_card", None)
    if presence is not None:
        stamps.append(float(getattr(presence, "written_at", 0.0) or 0.0))
    return max(stamps) if stamps else 0.0


def idle_seconds(state: Any, *, now: float | None = None) -> float:
    current = time.time() if now is None else float(now)
    stamp = last_interaction_at(state)
    if stamp <= 0:
        return 0.0
    return max(0.0, current - stamp)


def should_enter_dormant(
    state: Any,
    *,
    now: float | None = None,
    idle_sec: float = SPEAK_IDLE_DORMANT_SEC,
) -> bool:
    if bool(getattr(state, "speak_dormant", False)):
        return False
    return idle_seconds(state, now=now) >= float(idle_sec)


def needs_narrative_reinit(
    state: Any,
    *,
    now: float | None = None,
    idle_sec: float = SPEAK_IDLE_DORMANT_SEC,
) -> bool:
    """下次接入：已静默，或事实上已空闲超时。"""
    if bool(getattr(state, "speak_dormant", False)):
        return True
    stamp = last_interaction_at(state)
    if stamp <= 0:
        return False
    return idle_seconds(state, now=now) >= float(idle_sec)


def enter_speak_dormant(state: Any, *, reason: str = "idle_30m") -> dict[str, Any]:
    """Speak 侧静默：停主动开口意图，标记待再初始化。不 finalize Life 会话。"""
    state.speak_dormant = True
    state.speak_gate = "hold"
    state.pending_delivery_plan = None
    state.pending_character_handoff = None
    schedule = getattr(state, "character_rhythm_schedule", None)
    cancelled = 0
    if schedule is not None and hasattr(schedule, "executable_units"):
        for entry in list(schedule.executable_units or []):
            if getattr(entry, "status", "") == "pending":
                entry.status = "cancelled"
                cancelled += 1
    for trigger in ("idle", "append"):
        managers = getattr(state, "poll_frame_managers", None) or {}
        frame_mgr = managers.get(trigger)
        if frame_mgr is not None:
            frame_mgr.armed = False
            frame_mgr.next_fire_at = 0.0
    note = f"speak_dormant:{reason}"
    notes = getattr(state, "notes", None)
    if isinstance(notes, list):
        notes.append(note)
    cache = getattr(state, "director_cache", None)
    payload = {
        "dormant": True,
        "reason": reason,
        "cancelled_opens": cancelled,
        "idle_sec": idle_seconds(state),
    }
    if isinstance(cache, dict):
        cache["speak_dormant"] = dict(payload)
    return payload


def clear_narrative_for_reinit(state: Any) -> None:
    """清空 Speak 叙事短期态，供下次接入重新 init（独立于 Life）。"""
    from .narrative_card import NarrativeStageCard, SilenceLog
    from .plot_flow import PlotFlow
    from .presence_card import CharacterPresenceCard
    from .interaction_plan import PlotArc

    state.plot_flow = PlotFlow()
    state.plot_arc = PlotArc()
    state.presence_card = CharacterPresenceCard()
    state.narrative_card = NarrativeStageCard()
    state.silence_log = SilenceLog()
    state.screenwriter_continued_at_poll = 0
    state.presence_written_at_speak = 0
    state.speak_dormant = False
    if hasattr(state, "director_aligned_plot_fingerprint"):
        state.director_aligned_plot_fingerprint = ""
    if hasattr(state, "interaction_exchange_count"):
        state.interaction_exchange_count = 0
    if hasattr(state, "screenwriter_aligned_at_exchange"):
        state.screenwriter_aligned_at_exchange = 0
    if hasattr(state, "screenwriter_aligned_at_total"):
        state.screenwriter_aligned_at_total = 0
    cache = getattr(state, "director_cache", None)
    if isinstance(cache, dict):
        for key in (
            "screenwriter",
            "plot_flow",
            "plot_flow_unit",
            "plot_arc",
            "plot_arc_unit",
            "interaction_unit",
            "presence_unit",
            "presence_card_state",
            "narrative_card_state",
            "user_stage",
            "scene_event",
            "scene_seeds",
            "speak_dormant",
            "pending_unit_complete",
            "narrative_opening",
            "narrative_opening_delivered",
            "narrative_opening_placeholder_sent",
            "narrative_opening_is_placeholder",
            "screenwriter_init_scheduled",
            "screenwriter_inited_at",
            "screenwriter_agent_upgrade_scheduled",
            "director_init_scheduled",
        ):
            cache.pop(key, None)
    if hasattr(state, "last_character_trigger_id"):
        state.last_character_trigger_id = ""
    if hasattr(state, "pending_character_handoff"):
        state.pending_character_handoff = None
    notes = getattr(state, "notes", None)
    if isinstance(notes, list):
        notes.append("narrative_reinit:cleared")
