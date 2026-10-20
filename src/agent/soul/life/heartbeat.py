# -*- coding: utf-8 -*-
"""life 域心跳入口：landmark 规划/触发、surprise、scheduler digest。

实现知识住在 life/wiring 侧，heartbeat 零模块知识（wake-registration-prd）。
"""

from __future__ import annotations

from typing import Any

from agent.soul.evolution_capture import EvolutionCapture
from agent.soul.heartbeat.schedule.context import HeartbeatContext
from agent.soul.heartbeat.schedule.item import ChecklistItem, ChecklistTrigger
from agent.soul.handlers.api.actions import LifeAction


def wake_items(cfg) -> list[ChecklistItem]:
    c = cfg or _fallback_cfg()
    return [
        ChecklistItem(
            id="life-plan-landmark",
            domain="life",
            action=LifeAction.PLAN_LANDMARK,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.landmark_write_interval_sec,
            target="agent.soul.life.heartbeat:plan_landmark_entry",
            heavy=True,
        ),
        ChecklistItem(
            id="life-trigger-landmark",
            domain="life",
            action=LifeAction.TRIGGER_LANDMARKS,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.landmark_trigger_interval_sec,
            target="agent.soul.life.heartbeat:trigger_landmarks_entry",
        ),
        ChecklistItem(
            id="life-surprise",
            domain="life",
            action=LifeAction.TICK_SURPRISE,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.surprise_tick_interval_sec,
            payload={"elapsed_sec": c.surprise_tick_interval_sec},
            target="agent.soul.life.heartbeat:tick_surprise_entry",
        ),
        ChecklistItem(
            id="life-scheduler-digest",
            domain="life",
            action=LifeAction.RECORD_SCHEDULER_DIGEST,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.heartbeat_scan_interval_sec,
            target="agent.soul.life.heartbeat:scheduler_digest_entry",
        ),
    ]


def _fallback_cfg():
    from config.soul.config import SoulConfig

    return SoulConfig.default()


def plan_landmark_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    """landmark 规划：life worker 内执行 + 演化捕获 + 剧情 beat 发射。"""
    soul = ctx.soul
    life_worker = soul.workers.life
    detail = life_worker.submit(lambda: soul.execute_plan_landmark()).result()
    capture_report = None
    if detail.get("planned"):
        subjective_event = dict(detail.get("subjective_event", {}))
        if subjective_event.get("hint"):
            capture_report = EvolutionCapture.after_landmark_planned(
                soul,
                subjective_event,
            )
    if capture_report is not None:
        detail = {
            **detail,
            "capture_events": len(capture_report.events),
            "capture_outbound": capture_report.outbound_count,
            "incident_fsm_updates": capture_report.incident_count,
        }
    # 剧情链路（R6.2）：规划出的主观事件 → beat → speak 扮演
    from agent.soul.wiring.story import beat_from_subjective_event, emit_story_beats

    draft = beat_from_subjective_event(
        dict(detail.get("subjective_event", {})), source_tick="life-plan-landmark"
    ) if detail.get("planned") else None
    return {
        **detail,
        "story_beats": emit_story_beats(soul, [draft] if draft else []),
    }


def trigger_landmarks_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    soul = ctx.soul
    fills = soul.run_trigger_landmarks()
    capture_report = EvolutionCapture.after_landmark_filled(soul, _beats(fills))
    # 剧情链路（R6.2）：到点填补的 landmark → beat → speak 扮演
    from agent.soul.wiring.story import beats_from_landmark_fills, emit_story_beats

    story_beats = emit_story_beats(soul, beats_from_landmark_fills(fills))
    return {
        "filled": len(fills),
        "capture_events": len(capture_report.events),
        "capture_outbound": capture_report.outbound_count,
        "incident_fsm_updates": capture_report.incident_count,
        "story_beats": story_beats,
    }


def tick_surprise_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    soul = ctx.soul
    elapsed = float(payload.get("elapsed_sec") or getattr(soul.config, "surprise_tick_interval_sec", 0))
    detail = soul.run_surprise_tick(elapsed)
    capture_report = None
    if detail.get("triggered"):
        capture_report = EvolutionCapture.after_surprise(
            soul,
            hint=str(detail.get("narrative", "")),
            salience=float(detail.get("salience", 0.5)),
            emotion_text=str(detail.get("emotion_text", "")),
            emotion_intensity=float(detail.get("emotion_intensity", 0.0)),
            emotion_strength=str(detail.get("emotion_strength", "")),
        )
    if capture_report is not None:
        detail = {
            **detail,
            "capture_events": len(capture_report.events),
            "capture_outbound": capture_report.outbound_count,
            "incident_fsm_updates": capture_report.incident_count,
        }
    # 剧情链路（R6.2）：惊奇事件 → beat → speak 扮演
    from agent.soul.wiring.story import beat_from_surprise, emit_story_beats

    draft = beat_from_surprise(detail) if detail.get("triggered") else None
    return {
        **detail,
        "story_beats": emit_story_beats(soul, [draft] if draft else []),
    }


def scheduler_digest_entry(payload: dict, ctx: HeartbeatContext) -> Any:
    tasks_text = _format_recent_tasks(ctx.scheduler_engine)
    if not tasks_text.strip():
        return "skip empty"
    from agent.soul.request import SoulChannel, SoulDomain, SoulRequest

    return ctx.soul.dispatch(SoulRequest(
        domain=SoulDomain.life,
        action=LifeAction.RECORD_SCHEDULER_DIGEST,
        payload={"tasks_text": tasks_text},
        channel=SoulChannel.api,
    ))


def _beats(items: list[dict]):
    from agent.soul.evolution_capture import beats_from_dicts

    return beats_from_dicts(items)


def _format_recent_tasks(engine) -> str:
    if engine is None:
        return ""
    timeline = engine.list_timeline()
    completed = [
        t for t in timeline
        if hasattr(t, "status") and str(t.status.value) in ("done", "completed")
    ]
    if not completed:
        return ""
    parts = []
    for t in completed[-5:]:
        name = getattr(t, "name", "")
        result = getattr(t, "result", "") or ""
        if name:
            parts.append(f"- {name}: {str(result)[:80]}")
    return "\n".join(parts)
