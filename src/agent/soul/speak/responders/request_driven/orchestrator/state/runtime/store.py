from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from ..core.character_rhythm_schedule import CharacterRhythmSchedule
from ..core.delivery import DeliveryPlan
from ..core.interaction_plan import PlotArc
from ..core.narrative_card import NarrativeStageCard, SilenceLog
from ..core.outline import DialogueOutline, RhythmState
from ..core.plot_flow import PlotFlow
from ..core.poll import PollFrameManager
from ..core.presence_card import CharacterPresenceCard
from ..core.speak_agenda import CharacterSpeakAgenda


@dataclass
class SessionSchedulingState:
    session_id: str
    outline: DialogueOutline = field(default_factory=DialogueOutline)
    rhythm: RhythmState = field(default_factory=RhythmState)
    # 临场角色节奏表：会话内唯一一份（开口时刻 / 信息需求 / 导演私有心思）
    character_rhythm_schedule: CharacterRhythmSchedule = field(
        default_factory=CharacterRhythmSchedule
    )
    # 开口议程：导演戳优先，角色预约其次
    speak_agenda: CharacterSpeakAgenda = field(default_factory=CharacterSpeakAgenda)
    # 剧情流：编剧主表（交互轨迹 + 轻推）；临场卡为附带
    plot_flow: PlotFlow = field(default_factory=PlotFlow)
    # 剧情弧：场景大纲 + 交互单元队列（逐步推进）
    plot_arc: PlotArc = field(default_factory=PlotArc)
    poll_frame_managers: dict[str, PollFrameManager] = field(default_factory=dict)
    delivery_plan: DeliveryPlan | None = None
    pending_delivery_plan: DeliveryPlan | None = None
    user_intent: str = ""
    user_intent_confidence: float = 0.0
    speak_gate: str = "listen"
    director_cache: dict[str, Any] = field(default_factory=dict)
    # 导演下一轮预测：pending 本轮写出；active 下轮角色消费
    pending_next_turn_guide: dict[str, Any] = field(default_factory=dict)
    active_next_turn_guide: dict[str, Any] = field(default_factory=dict)
    # 角色临场状态卡片（编剧写入 → 注入角色；导演只消费）
    presence_card: CharacterPresenceCard = field(default_factory=CharacterPresenceCard)
    # 叙事舞台 + 多轮静默元数据日志
    narrative_card: NarrativeStageCard = field(default_factory=NarrativeStageCard)
    silence_log: SilenceLog = field(default_factory=SilenceLog)
    last_real_user_text: str = ""
    # 命运骰开口欲软评分（0~100），跨帧连续漫步
    fate_speak_desire: int | None = None
    # 编剧：角色可见开口计数与写卡锚点
    agent_speak_count: int = 0
    presence_written_at_speak: int = 0
    last_counted_speak_turn: int = 0
    last_agent_speak_at: float = 0.0
    last_user_speak_at: float = 0.0
    poll_seq: int = 0
    # 用户↔角色已完成的往来轮次（双方都开口才计；唤醒后清零）
    interaction_exchange_count: int = 0
    # 最近一次检查时的往来水位 / unit 总数（往来水位随清零归 0）
    screenwriter_aligned_at_exchange: int = 0
    screenwriter_aligned_at_total: int = 0
    # 角色后台预约轮询水位（独立于导演/编剧唤醒）
    character_book_polled_at_exchange: int = 0
    character_book_polled_at_total: int = 0
    # 导演上次对齐时的剧情 unit 指纹；到点后未变动则跳过导演
    director_aligned_plot_fingerprint: str = ""
    # 编剧：最近一次按 poll 续写剧情的序号
    screenwriter_continued_at_poll: int = 0
    # Speak 独立：超时无交互后静默，下次接入再初始化叙事
    speak_dormant: bool = False
    # 导演本轮动作终止：冻结上下文改写/重排，直到新一轮询或用户入站
    director_context_frozen: bool = False
    # 导演主动 due：交给角色生成下一组可见内容（用户直回不走此字段）
    pending_character_handoff: dict[str, Any] | None = None
    # 角色回复 trigger 去重：同一 trigger_id 禁止双投递
    last_character_trigger_id: str = ""
    notes: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "outline": self.outline.snapshot(),
            "rhythm": self.rhythm.snapshot(),
            "character_rhythm_schedule": self.character_rhythm_schedule.snapshot(),
            "speak_agenda": self.speak_agenda.snapshot(),
            "plot_flow": self.plot_flow.snapshot(),
            "plot_arc": self.plot_arc.snapshot(),
            "poll_frame_managers": {
                key: mgr.snapshot() for key, mgr in self.poll_frame_managers.items()
            },
            "delivery_plan": (
                self.delivery_plan.snapshot() if self.delivery_plan is not None else None
            ),
            "pending_delivery_plan": (
                self.pending_delivery_plan.snapshot()
                if self.pending_delivery_plan is not None
                else None
            ),
            "user_intent": self.user_intent,
            "user_intent_confidence": self.user_intent_confidence,
            "speak_gate": self.speak_gate,
            "director_cache": dict(self.director_cache),
            "pending_next_turn_guide": dict(self.pending_next_turn_guide),
            "active_next_turn_guide": dict(self.active_next_turn_guide),
            "presence_card": self.presence_card.snapshot(),
            "narrative_card": self.narrative_card.snapshot(),
            "silence_log": self.silence_log.snapshot(),
            "last_real_user_text": self.last_real_user_text,
            "fate_speak_desire": self.fate_speak_desire,
            "agent_speak_count": self.agent_speak_count,
            "presence_written_at_speak": self.presence_written_at_speak,
            "last_counted_speak_turn": self.last_counted_speak_turn,
            "last_agent_speak_at": self.last_agent_speak_at,
            "last_user_speak_at": self.last_user_speak_at,
            "poll_seq": self.poll_seq,
            "interaction_exchange_count": self.interaction_exchange_count,
            "screenwriter_aligned_at_exchange": self.screenwriter_aligned_at_exchange,
            "screenwriter_aligned_at_total": self.screenwriter_aligned_at_total,
            "character_book_polled_at_exchange": self.character_book_polled_at_exchange,
            "character_book_polled_at_total": self.character_book_polled_at_total,
            "director_aligned_plot_fingerprint": self.director_aligned_plot_fingerprint,
            "screenwriter_continued_at_poll": self.screenwriter_continued_at_poll,
            "speak_dormant": bool(self.speak_dormant),
            "director_context_frozen": self.director_context_frozen,
            "pending_character_handoff": (
                dict(self.pending_character_handoff)
                if self.pending_character_handoff is not None
                else None
            ),
            "last_character_trigger_id": self.last_character_trigger_id,
            "notes": list(self.notes),
        }


class StateStore:
    """orchestrator 调度态存储：大纲、节奏、帧数管理器、交付计划。"""

    def __init__(self) -> None:
        self._states: dict[str, SessionSchedulingState] = {}
        self._lock = threading.Lock()

    def session(self, session_id: str) -> SessionSchedulingState:
        sid = session_id.strip()
        with self._lock:
            if sid not in self._states:
                self._states[sid] = SessionSchedulingState(session_id=sid)
            return self._states[sid]

    def poll_frame_manager(self, session_id: str, trigger: str) -> PollFrameManager:
        state = self.session(session_id)
        key = trigger.strip()
        if key not in state.poll_frame_managers:
            # idle / append：用户后阶梯 5→15→30…；append 稍不易跳过
            if key == "idle":
                state.poll_frame_managers[key] = PollFrameManager(
                    session_id=session_id.strip(),
                    trigger="idle",
                    p_floor=0.12,
                    jitter_ratio=0.2,
                )
            else:
                state.poll_frame_managers[key] = PollFrameManager(
                    session_id=session_id.strip(),
                    trigger=key,  # type: ignore[arg-type]
                    p_floor=0.2,
                    jitter_ratio=0.2,
                )
        return state.poll_frame_managers[key]

    def set_delivery_plan(
        self,
        session_id: str,
        plan: DeliveryPlan | None,
        *,
        pending: bool = False,
    ) -> None:
        state = self.session(session_id)
        if pending:
            state.pending_delivery_plan = plan
        else:
            state.delivery_plan = plan

    def take_pending_delivery_plan(self, session_id: str) -> DeliveryPlan | None:
        state = self.session(session_id)
        plan = state.pending_delivery_plan
        state.pending_delivery_plan = None
        return plan

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        with self._lock:
            self._states.pop(sid, None)

    def snapshot(self, session_id: str) -> dict[str, Any]:
        return self.session(session_id).snapshot()
