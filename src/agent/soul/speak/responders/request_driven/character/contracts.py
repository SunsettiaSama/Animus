from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
    DeliveryPlan,
)
from agent.soul.speak.responders.request_driven.timeline import RoleTimeline

CharacterReplyOrigin = Literal["user", "director", "booked"]


def new_trigger_id(prefix: str = "trigger") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class DeliveryIntent:
    """交付节奏约束；不含可见正文。"""

    speak_gate: str = "speak"
    continuity: str = "finish"
    plan_id: str = ""
    wait_ms: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "speak_gate": self.speak_gate,
            "continuity": self.continuity,
            "plan_id": self.plan_id,
            "wait_ms": int(self.wait_ms),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DeliveryIntent:
        if not isinstance(data, dict):
            return cls()
        return cls(
            speak_gate=str(data.get("speak_gate") or "speak").strip() or "speak",
            continuity=str(data.get("continuity") or "finish").strip() or "finish",
            plan_id=str(data.get("plan_id") or "").strip(),
            wait_ms=int(data.get("wait_ms") or 0),
        )


@dataclass(frozen=True)
class NarrativeSnapshot:
    """编剧叙事只读快照：角色消费，不得回写剧情状态。"""

    plot_arc_summary: str = ""
    active_unit_id: str = ""
    active_unit_intent: str = ""
    plot_outline_text: str = ""
    plot_flow_text: str = ""
    director_focus: str = ""
    director_intent: str = ""
    director_direction: str = ""
    director_exit: str = ""
    # 节奏扩充（「你」口吻）
    director_detail: str = ""
    director_inner: str = ""
    director_transition: str = ""
    director_stance: str = ""
    presence_mood: str = ""
    presence_brief: str = ""
    presence_speak_desire: int | None = None
    presence_fate_tendency: str = ""
    presence_render: str = ""
    user_identity: str = ""
    user_activity: str = ""
    interaction_channel: str = ""
    scene_event: str = ""
    silence_log_text: str = ""
    interaction_record_text: str = ""
    behavior_guide: str = ""
    script_hint: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "plot_arc_summary": self.plot_arc_summary,
            "active_unit_id": self.active_unit_id,
            "active_unit_intent": self.active_unit_intent,
            "plot_outline_text": self.plot_outline_text,
            "plot_flow_text": self.plot_flow_text,
            "director_focus": self.director_focus,
            "director_intent": self.director_intent,
            "director_direction": self.director_direction,
            "director_exit": self.director_exit,
            "director_detail": self.director_detail,
            "director_inner": self.director_inner,
            "director_transition": self.director_transition,
            "director_stance": self.director_stance,
            "presence_mood": self.presence_mood,
            "presence_brief": self.presence_brief,
            "presence_speak_desire": self.presence_speak_desire,
            "presence_fate_tendency": self.presence_fate_tendency,
            "presence_render": self.presence_render,
            "user_identity": self.user_identity,
            "user_activity": self.user_activity,
            "interaction_channel": self.interaction_channel,
            "scene_event": self.scene_event,
            "silence_log_text": self.silence_log_text,
            "interaction_record_text": self.interaction_record_text,
            "behavior_guide": self.behavior_guide,
            "script_hint": self.script_hint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NarrativeSnapshot:
        if not isinstance(data, dict):
            return cls()
        desire_raw = data.get("presence_speak_desire")
        desire = int(desire_raw) if desire_raw is not None and str(desire_raw).strip() != "" else None
        return cls(
            plot_arc_summary=str(data.get("plot_arc_summary") or "").strip(),
            active_unit_id=str(data.get("active_unit_id") or "").strip(),
            active_unit_intent=str(data.get("active_unit_intent") or "").strip(),
            plot_outline_text=str(data.get("plot_outline_text") or "").strip(),
            plot_flow_text=str(data.get("plot_flow_text") or "").strip(),
            director_focus=str(data.get("director_focus") or "").strip(),
            director_intent=str(data.get("director_intent") or "").strip(),
            director_direction=str(data.get("director_direction") or "").strip(),
            director_exit=str(data.get("director_exit") or "").strip(),
            director_detail=str(data.get("director_detail") or "").strip(),
            director_inner=str(data.get("director_inner") or "").strip(),
            director_transition=str(data.get("director_transition") or "").strip(),
            director_stance=str(data.get("director_stance") or "").strip(),
            presence_mood=str(data.get("presence_mood") or "").strip(),
            presence_brief=str(data.get("presence_brief") or "").strip(),
            presence_speak_desire=desire,
            presence_fate_tendency=str(data.get("presence_fate_tendency") or "").strip(),
            presence_render=str(data.get("presence_render") or "").strip(),
            user_identity=str(data.get("user_identity") or "").strip(),
            user_activity=str(data.get("user_activity") or "").strip(),
            interaction_channel=str(data.get("interaction_channel") or "").strip(),
            scene_event=str(data.get("scene_event") or "").strip(),
            silence_log_text=str(data.get("silence_log_text") or "").strip(),
            interaction_record_text=str(data.get("interaction_record_text") or "").strip(),
            behavior_guide=str(data.get("behavior_guide") or "").strip(),
            script_hint=str(data.get("script_hint") or "").strip(),
        )

    def render_director_instruction(self) -> str:
        lines: list[str] = []
        detail = self.director_detail.strip() or self.director_focus.strip()
        inner = self.director_inner.strip() or self.director_intent.strip()
        transition = self.director_transition.strip() or self.director_direction.strip()
        stance = self.director_stance.strip() or self.director_exit.strip()
        if detail:
            lines.append(f"你手头：{detail}")
        if inner:
            lines.append(f"你在想：{inner}")
        if transition:
            lines.append(f"你怎么过渡：{transition}")
        if stance:
            lines.append(f"你的姿态：{stance}")
        return "\n".join(lines)


@dataclass
class CharacterReplyRequest:
    """统一角色回复请求：用户直入与导演主动共用。"""

    origin: CharacterReplyOrigin
    session_id: str
    turn_index: int
    trigger_id: str
    user_text: str = ""
    director_cue: str = ""
    reason: str = ""
    narrative: NarrativeSnapshot = field(default_factory=NarrativeSnapshot)
    delivery_intent: DeliveryIntent = field(default_factory=DeliveryIntent)
    executable_unit_id: str = ""
    plot_unit_ids: tuple[str, ...] = ()
    created_at: float = 0.0

    def __post_init__(self) -> None:
        origin = str(self.origin or "").strip().lower()
        if origin not in ("user", "director", "booked"):
            raise ValueError(f"invalid CharacterReplyRequest.origin={self.origin!r}")
        self.origin = origin  # type: ignore[assignment]
        self.session_id = str(self.session_id or "").strip()
        self.turn_index = int(self.turn_index or 0)
        self.trigger_id = str(self.trigger_id or "").strip() or new_trigger_id(self.origin)
        self.user_text = str(self.user_text or "").strip()
        self.director_cue = str(self.director_cue or "").strip()
        self.reason = str(self.reason or "").strip()
        self.executable_unit_id = str(self.executable_unit_id or "").strip()
        ids = tuple(str(x).strip() for x in (self.plot_unit_ids or ()) if str(x).strip())
        self.plot_unit_ids = ids
        if self.created_at <= 0:
            self.created_at = time.time()
        if self.origin == "user" and not self.user_text:
            raise ValueError("CharacterReplyRequest(origin=user) requires user_text")
        if self.origin in ("director", "booked") and self.user_text:
            # 导演/预约主动不得把用户原文塞进请求；唤醒信号走 director_cue
            self.user_text = ""

    @property
    def effective_user_text(self) -> str:
        """角色生成入口文本：用户直入用原文；主动唤醒用空串（cue 不进用户账本）。"""
        if self.origin == "user":
            return self.user_text
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "trigger_id": self.trigger_id,
            "user_text": self.user_text,
            "director_cue": self.director_cue,
            "reason": self.reason,
            "narrative": self.narrative.snapshot(),
            "delivery_intent": self.delivery_intent.snapshot(),
            "executable_unit_id": self.executable_unit_id,
            "plot_unit_ids": list(self.plot_unit_ids),
            "created_at": float(self.created_at),
            # 兼容 handoff 消费侧既有字段名
            "kind": "silence" if self.origin in ("director", "booked") else "user",
            "continuity": self.delivery_intent.continuity,
            "speak_gate": self.delivery_intent.speak_gate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CharacterReplyRequest | None:
        if not isinstance(data, dict) or not data:
            return None
        origin_raw = str(data.get("origin") or "").strip().lower()
        if origin_raw not in ("user", "director", "booked"):
            raise ValueError(
                f"CharacterReplyRequest.origin must be user|director|booked, got {origin_raw!r}"
            )
        narrative = NarrativeSnapshot.from_dict(
            data.get("narrative") if isinstance(data.get("narrative"), dict) else None
        )
        delivery = DeliveryIntent.from_dict(
            data.get("delivery_intent")
            if isinstance(data.get("delivery_intent"), dict)
            else {
                "speak_gate": data.get("speak_gate") or "speak",
                "continuity": data.get("continuity") or "finish",
                "plan_id": data.get("plan_id") or "",
            }
        )
        plot_ids_raw = data.get("plot_unit_ids") or ()
        if isinstance(plot_ids_raw, str):
            plot_ids = (plot_ids_raw.strip(),) if plot_ids_raw.strip() else ()
        elif isinstance(plot_ids_raw, (list, tuple)):
            plot_ids = tuple(str(x).strip() for x in plot_ids_raw if str(x).strip())
        else:
            plot_ids = ()
        user_text = str(data.get("user_text") or "").strip()
        director_cue = str(data.get("director_cue") or "").strip()
        if origin_raw in ("director", "booked"):
            user_text = ""
            if not director_cue:
                director_cue = "（系统：按台本推进本拍演出。）"
        return cls(
            origin=origin_raw,  # type: ignore[arg-type]
            session_id=str(data.get("session_id") or "").strip(),
            turn_index=int(data.get("turn_index") or 0),
            trigger_id=str(data.get("trigger_id") or "").strip(),
            user_text=user_text,
            director_cue=director_cue,
            reason=str(data.get("reason") or "").strip(),
            narrative=narrative,
            delivery_intent=delivery,
            executable_unit_id=str(data.get("executable_unit_id") or "").strip(),
            plot_unit_ids=plot_ids,
            created_at=float(data.get("created_at") or 0.0),
        )


@dataclass
class CharacterReplyResult:
    """角色层统一产出：可见正文只来自这里。"""

    origin: CharacterReplyOrigin
    trigger_id: str
    session_id: str
    turn_index: int
    raw: str
    answer_text: str
    delivery_plan: DeliveryPlan
    timeline: RoleTimeline | None = None
    parsed: Any = None
    notes: list[str] = field(default_factory=list)
    consumed_executable_unit_id: str = ""
    consumed_plot_unit_ids: tuple[str, ...] = ()
    consumed_memory_unit_ids: tuple[str, ...] = ()
    consumed_share_texts: tuple[str, ...] = ()
    consumed_share_indices: tuple[int, ...] = ()
    notes_to_director: tuple[str, ...] = ()
    notes_to_screenwriter: tuple[str, ...] = ()
    chose_silence: bool = False

    @property
    def used_role_timeline(self) -> bool:
        return self.timeline is not None and bool(self.timeline.ops)

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "trigger_id": self.trigger_id,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "raw": self.raw,
            "answer_text": self.answer_text,
            "delivery_plan": self.delivery_plan.snapshot() if self.delivery_plan is not None else None,
            "notes": list(self.notes),
            "consumed_executable_unit_id": self.consumed_executable_unit_id,
            "consumed_plot_unit_ids": list(self.consumed_plot_unit_ids),
            "consumed_memory_unit_ids": list(self.consumed_memory_unit_ids),
            "consumed_share_texts": list(self.consumed_share_texts),
            "consumed_share_indices": list(self.consumed_share_indices),
            "notes_to_director": list(self.notes_to_director),
            "notes_to_screenwriter": list(self.notes_to_screenwriter),
            "chose_silence": bool(self.chose_silence),
            "used_role_timeline": self.used_role_timeline,
        }
