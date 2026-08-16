from __future__ import annotations

from typing import Any

from .contracts import (
    CharacterReplyOrigin,
    CharacterReplyRequest,
    DeliveryIntent,
    NarrativeSnapshot,
    new_trigger_id,
)
from .interaction import export_interaction_record


REMOTE_TEXT_CHANNEL = (
    "这个端口是你对外发消息的渠道。对方在远程通过文字跟你通信，不在你身边。"
    "你发的是短消息，一条一条发。"
    "手头动作已经在导演材料里写好了，消息里不用再写动作。"
)


def _lookup_executable_unit(state: Any, unit_id: str):
    uid = str(unit_id or "").strip()
    if not uid:
        return None
    rhythm = getattr(state, "character_rhythm_schedule", None)
    units = list(getattr(rhythm, "executable_units", None) or [])
    for entry in units:
        if str(getattr(entry, "unit_id", "") or "").strip() == uid:
            return entry
    return None


def build_narrative_snapshot(
    state: Any,
    *,
    origin: CharacterReplyOrigin | str = "",
    user_text: str = "",
    executable_unit_id: str = "",
) -> NarrativeSnapshot:
    """从会话状态抽取只读叙事快照，不回写。"""
    plot_arc = getattr(state, "plot_arc", None)
    plot_arc_summary = ""
    active_unit_id = ""
    active_unit_intent = ""
    if plot_arc is not None and getattr(plot_arc, "ready", False):
        plot_arc_summary = str(getattr(plot_arc, "summary", "") or "").strip()
        active = plot_arc.active_unit() if hasattr(plot_arc, "active_unit") else None
        if active is not None:
            active_unit_id = str(getattr(active, "unit_id", "") or "").strip()
            active_unit_intent = str(getattr(active, "intent", "") or "").strip()

    plot_flow = getattr(state, "plot_flow", None)
    plot_flow_text = ""
    if plot_flow is not None and getattr(plot_flow, "ready", False):
        plot_flow_text = str(plot_flow.render_for_inject() or "").strip()
    plot_outline_text = ""
    if plot_arc is not None and getattr(plot_arc, "ready", False):
        plot_outline_text = str(plot_arc.render_for_inject() or "").strip()

    presence_card = getattr(state, "presence_card", None)
    presence_render = ""
    if presence_card is not None and getattr(presence_card, "ready", False):
        presence_render = str(presence_card.render() or "").strip()

    narrative_card = getattr(state, "narrative_card", None)
    silence_log = getattr(state, "silence_log", None)
    silence_log_text = ""
    if silence_log is not None and getattr(silence_log, "ready", False):
        silence_log_text = str(silence_log.render() or "").strip()

    origin_s = str(origin or "").strip().lower()
    if origin_s == "user" and str(user_text or "").strip():
        # 用户直入：以用户原文为准，不沿用旧静默状态
        interaction_channel = (
            f"{REMOTE_TEXT_CHANNEL}\n本拍是对方刚发来的文字，不是静默场面。"
        )
        silence_log_text = ""
        user_activity = "正在与你文字往来"
    else:
        interaction_channel = str(
            getattr(narrative_card, "interaction_mode", "") or ""
        ).strip()
        if interaction_channel:
            interaction_channel = (
                f"{REMOTE_TEXT_CHANNEL}\n本拍交互形态：{interaction_channel}。"
            )
        else:
            interaction_channel = REMOTE_TEXT_CHANNEL
        user_activity = str(getattr(narrative_card, "user_activity", "") or "").strip()

    bound_unit = _lookup_executable_unit(state, executable_unit_id)
    interaction_record_text = ""
    if getattr(state, "director_cache", None) is not None:
        interaction_record_text = export_interaction_record(state).render_for_character()

    detail = ""
    inner = ""
    transition = ""
    stance = ""
    if bound_unit is not None:
        detail = str(getattr(bound_unit, "detail", "") or getattr(bound_unit, "focus", "") or "").strip()
        inner = str(getattr(bound_unit, "inner", "") or getattr(bound_unit, "intent", "") or "").strip()
        transition = str(
            getattr(bound_unit, "transition", "") or getattr(bound_unit, "direction", "") or ""
        ).strip()
        stance = str(
            getattr(bound_unit, "stance", "") or getattr(bound_unit, "exit", "") or ""
        ).strip()

    return NarrativeSnapshot(
        plot_arc_summary=plot_arc_summary,
        active_unit_id=active_unit_id,
        active_unit_intent=active_unit_intent,
        plot_outline_text=plot_outline_text,
        plot_flow_text=plot_flow_text,
        director_focus=detail,
        director_intent=inner,
        director_direction=transition,
        director_exit=stance,
        director_detail=detail,
        director_inner=inner,
        director_transition=transition,
        director_stance=stance,
        presence_mood=str(getattr(presence_card, "mood", "") or "").strip(),
        presence_brief=str(getattr(presence_card, "brief", "") or "").strip(),
        presence_speak_desire=getattr(presence_card, "speak_desire", None),
        presence_fate_tendency=str(getattr(presence_card, "fate_tendency", "") or "").strip(),
        presence_render=presence_render,
        user_identity=str(getattr(narrative_card, "user_identity", "") or "").strip(),
        user_activity=user_activity,
        interaction_channel=interaction_channel,
        scene_event=str(getattr(narrative_card, "scene_event", "") or "").strip(),
        silence_log_text="",
        interaction_record_text=interaction_record_text,
        behavior_guide="",
        script_hint="",
    )


def bind_delivery_step_for_user(
    state: Any,
    *,
    session_id: str,
    turn_index: int,
) -> tuple[str, tuple[str, ...], str]:
    """用户输入独占一个 step。

    优先消费当前 active 剧情步骤对应的预编排可执行 unit；
    保留队列中其余有剧情绑定的步骤，只撤销无剧情绑定的占位预约。
    """
    import time as _time

    from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
        ExecutableUnit,
    )

    rhythm = getattr(state, "character_rhythm_schedule", None)
    if rhythm is None:
        return "", (), ""

    now = _time.time()
    due = list(rhythm.due_units(now=now) or [])
    pending = list(rhythm.pending_units() or [])
    plot_bound = [
        u
        for u in (due + pending)
        if getattr(u, "status", "") in ("pending", "reserved")
        and tuple(getattr(u, "plot_unit_ids", ()) or ())
    ]

    active_id = ""
    plot_arc = getattr(state, "plot_arc", None)
    if plot_arc is not None and getattr(plot_arc, "ready", False):
        active = plot_arc.active_unit() if hasattr(plot_arc, "active_unit") else None
        if active is not None:
            active_id = str(getattr(active, "unit_id", "") or "").strip()

    consume = None
    if active_id and plot_bound:
        for entry in plot_bound:
            if active_id in tuple(getattr(entry, "plot_unit_ids", ()) or ()):
                consume = entry
                break
    if consume is None and plot_bound:
        consume = min(plot_bound, key=lambda e: float(getattr(e, "open_at", 0.0) or 0.0))

    for scheduled in rhythm.executable_units:
        if scheduled.status != "pending":
            continue
        if consume is not None and scheduled.unit_id == consume.unit_id:
            continue
        # 预编排剧情队列保留，只撤无绑定的时间占位
        if tuple(getattr(scheduled, "plot_unit_ids", ()) or ()):
            continue
        scheduled.status = "cancelled"

    state.pending_character_handoff = None

    if consume is not None:
        consume.open_at = now
        plot_ids = tuple(consume.plot_unit_ids)
        state.character_rhythm_schedule = rhythm
        state.director_cache["character_rhythm_schedule"] = rhythm.snapshot()
        return consume.unit_id, plot_ids, ""

    plot_ids: tuple[str, ...] = ()
    if active_id:
        plot_ids = (active_id,)
    step_id = f"exec-user-reply-{session_id[-8:]}-{int(turn_index or 0)}"
    entry = ExecutableUnit(
        unit_id=step_id,
        open_at=now,
        plot_unit_ids=plot_ids,
        reason="user_ingress_bind",
        status="pending",
    )
    rhythm.executable_units.append(entry)
    state.character_rhythm_schedule = rhythm
    state.director_cache["character_rhythm_schedule"] = rhythm.snapshot()
    return step_id, plot_ids, ""


def build_character_reply_request(
    *,
    origin: CharacterReplyOrigin,
    session_id: str,
    turn_index: int,
    state: Any,
    user_text: str = "",
    director_cue: str = "",
    reason: str = "",
    trigger_id: str = "",
    executable_unit_id: str = "",
    plot_unit_ids: tuple[str, ...] | list[str] = (),
    delivery_intent: DeliveryIntent | None = None,
    bind_user_step: bool = True,
) -> CharacterReplyRequest:
    exec_id = str(executable_unit_id or "").strip()
    plot_ids = tuple(plot_unit_ids or ())
    if origin == "user" and bind_user_step and not exec_id:
        exec_id, plot_ids, _ignored = bind_delivery_step_for_user(
            state,
            session_id=session_id,
            turn_index=turn_index,
        )
    narrative = build_narrative_snapshot(
        state,
        origin=origin,
        user_text=user_text,
        executable_unit_id=exec_id,
    )
    intent = delivery_intent or DeliveryIntent(
        speak_gate=str(getattr(state, "speak_gate", "") or "speak").strip() or "speak",
        continuity="finish",
        plan_id=f"{origin}-{session_id}-{turn_index}",
    )
    tid = trigger_id.strip() if trigger_id else ""
    if not tid:
        if origin in ("director", "booked") and exec_id:
            tid = f"{origin}:{exec_id}:{reason or 'open'}"
        elif origin == "user":
            tid = f"user:{session_id}:{turn_index}"
            if exec_id:
                tid = f"user:{exec_id}:{turn_index}"
        else:
            tid = new_trigger_id(origin)
    return CharacterReplyRequest(
        origin=origin,
        session_id=session_id,
        turn_index=turn_index,
        trigger_id=tid,
        user_text=user_text if origin == "user" else "",
        director_cue=director_cue if origin in ("director", "booked") else "",
        reason=reason,
        narrative=narrative,
        delivery_intent=intent,
        executable_unit_id=exec_id,
        plot_unit_ids=plot_ids,
    )


def context_cards_from_narrative(
    narrative: NarrativeSnapshot,
    *,
    dialogue_frame: str = "",
    memory_texts: tuple[str, ...] = (),
    share_texts: tuple[str, ...] = (),
    user_text: str = "",
) -> list[tuple[str, str]]:
    """组装角色 Agent 的上下文卡片（只读）。记忆和分享作为独立卡片压入。"""
    cards: list[tuple[str, str]] = []
    if str(user_text or "").strip():
        cards.append(("即时往来", str(user_text).strip()))
    if narrative.interaction_record_text.strip():
        cards.append(("交互记录", narrative.interaction_record_text.strip()))
    if narrative.interaction_channel.strip():
        cards.append(("交互通道", narrative.interaction_channel.strip()))
    if narrative.plot_outline_text.strip():
        cards.append(("故事线", narrative.plot_outline_text))
    if narrative.plot_flow_text.strip():
        cards.append(("此刻情景", narrative.plot_flow_text))
    instruction = narrative.render_director_instruction()
    if instruction:
        cards.append(("导演指令", instruction))
    if narrative.user_identity.strip() or narrative.user_activity.strip():
        stage_lines = []
        if narrative.user_identity.strip():
            stage_lines.append(f"身份：{narrative.user_identity.strip()}")
        if narrative.user_activity.strip():
            stage_lines.append(f"正在做：{narrative.user_activity.strip()}")
        cards.append(("用户舞台", "\n".join(stage_lines)))
    elif narrative.scene_event.strip() and not narrative.plot_flow_text.strip():
        cards.append(("临场事件", narrative.scene_event.strip()))
    if narrative.presence_render.strip():
        cards.append(("临场状态", narrative.presence_render))
    if memory_texts:
        body = "\n".join(f"- {t.strip()}" for t in memory_texts if str(t).strip())
        if body:
            cards.append(("记忆卡片", body))
    if share_texts:
        body = "\n".join(f"- {t.strip()}" for t in share_texts if str(t).strip())
        if body:
            cards.append(("分享卡片", body))
    if dialogue_frame.strip() and not narrative.interaction_record_text.strip():
        cards.append(("对话轨迹", dialogue_frame.strip()))
    return cards