from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..contracts import Clock
from .desire import DesireArc
from .director_log import DirectorBeat
from .floor import FloorPhase
from .on_scene import OnSceneState
from .review import RhythmReview


def light_stamp(ts: float) -> tuple[int, int, int, int]:
    """轻量时间：月、日、时、分（不含年/秒）。"""
    dt = datetime.fromtimestamp(ts)
    return dt.month, dt.day, dt.hour, dt.minute


@dataclass(frozen=True)
class ShareEvent:
    """待分享事件：台上还没说出口的冲动/材料（叙述驱动，无门控分数）。"""

    title: str
    detail: str = ""
    urgency: float = 0.0
    event_id: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            object.__setattr__(self, "event_id", uuid4().hex[:10])

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "detail": self.detail,
        }

    def one_line(self) -> str:
        base = self.title.strip()
        if self.detail.strip():
            return f"{base}（{self.detail.strip()[:80]}）"
        return base


@dataclass
class AffectState:
    """情感标签：给软指令阅读，不是数值门控。"""

    intensity: float = 0.0
    label: str = "平静"
    valence: str = "neutral"

    def clamp(self) -> None:
        self.intensity = max(0.0, min(1.0, float(self.intensity)))

    def snapshot(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "valence": self.valence,
            "intensity": self.intensity,
        }


@dataclass
class CastPortraits:
    """短角色卡：给开口指令中枢读，不是给回复者念长文。"""

    agent: str = "阿栖：自然、简短、有温度，偶尔会主动接话。"
    user: str = "搭档：直接、爱把问题说清楚，一起抠架构。"

    def snapshot(self) -> dict[str, Any]:
        return {"agent": self.agent, "user": self.user}


@dataclass(frozen=True)
class HistoryBeat:
    speaker: str
    text: str
    month: int
    day: int
    hour: int
    minute: int

    @classmethod
    def at(cls, speaker: str, text: str, *, ts: float) -> HistoryBeat:
        month, day, hour, minute = light_stamp(ts)
        return cls(
            speaker=speaker,
            text=text,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
        )

    def time_label(self) -> str:
        return f"{self.month:02d}-{self.day:02d} {self.hour:02d}:{self.minute:02d}"

    def one_line(self, *, limit: int = 60) -> str:
        body = " ".join(self.text.strip().split())
        if len(body) > limit:
            body = body[:limit] + "…"
        return f"[{self.time_label()}] {self.speaker}:{body}"

    def meta_snapshot(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "month": self.month,
            "day": self.day,
            "hour": self.hour,
            "minute": self.minute,
            "time": self.time_label(),
        }


@dataclass
class StageState:
    """
    会话舞台状态（可变、持续管理）。

    由历史轮次、agent 当下态、分享欲/情感驱动；
    开口指令中枢每拍读取冻结快照，决定要不要说。
    """

    session_id: str = "demo"
    turn_index: int = 0
    history: list[HistoryBeat] = field(default_factory=list)
    share_queue: list[ShareEvent] = field(default_factory=list)
    affect: AffectState = field(default_factory=AffectState)
    cast: CastPortraits = field(default_factory=CastPortraits)
    agent_status: str = "站在侧幕，听着，随时可以接一句。"
    # 回复侧长材料（compose 全量注入；节奏只看 cast 短卡）
    agent_persona: str = ""
    agent_presence: str = ""
    interactor_portrait: str = ""
    agent_scene: str = ""
    memory_hint: str = ""
    poll_index: int = 0
    proactive_count: int = 0
    created_at: float = 0.0
    last_user_at: float = 0.0
    last_agent_at: float = 0.0
    last_proactive_at: float = 0.0
    last_activity_at: float = 0.0
    silence_armed: bool = False
    desire_arc: DesireArc | None = None
    rhythm_review: RhythmReview | None = None
    floor_phase: FloorPhase = "clear"
    director_beats: list[DirectorBeat] = field(default_factory=list)
    # 上一拍已分享出队的条目；poll 可 tag=expand 展开检索（队列本身不再持有）
    last_shared: ShareEvent | None = None
    # 临场状态：由 rhythm 触发异步刷新，经 inbound 注入；compose 只读最新份
    on_scene: OnSceneState = field(default_factory=OnSceneState)
    beats_since_on_scene: int = 0
    on_scene_pending: bool = False
    beats_since_affect: int = 0
    # 连续同 gate 计数（伪学习警示用）
    last_gate: str = ""
    gate_streak: int = 0

    # --- desire arc / review ---
    def set_desire_arc(self, arc: DesireArc) -> None:
        """覆盖写弧；旧弧直接丢掉，不做对照。"""
        self.desire_arc = arc

    def set_rhythm_review(self, review: RhythmReview | None) -> None:
        self.rhythm_review = review

    def set_floor(self, phase: FloorPhase) -> None:
        self.floor_phase = phase

    def note_gate(self, gate: str) -> int:
        """记录本拍 gate，返回更新后的连续次数。"""
        token = gate.strip()
        if token and token == self.last_gate:
            self.gate_streak += 1
        else:
            self.last_gate = token
            self.gate_streak = 1 if token else 0
        return self.gate_streak

    def record_director(self, beat: DirectorBeat, *, keep: int = 32) -> None:
        self.director_beats.append(beat)
        self.note_gate(beat.gate)
        if len(self.director_beats) > keep:
            self.director_beats = self.director_beats[-keep:]

    def recent_directors(self, limit: int = 2) -> tuple[DirectorBeat, ...]:
        return tuple(self.director_beats[-limit:])

    # --- timeline ---
    def ensure_timeline(self, clock: Clock) -> None:
        now = clock.now()
        if self.created_at <= 0:
            self.created_at = now
            self.last_activity_at = now
            self.last_user_at = now
            self.last_agent_at = now

    def mark_user(self, clock: Clock) -> None:
        now = clock.now()
        self.ensure_timeline(clock)
        self.last_user_at = now
        self.last_activity_at = now
        self.floor_phase = "clear"

    def mark_agent(self, clock: Clock, *, proactive: bool) -> None:
        now = clock.now()
        self.ensure_timeline(clock)
        self.last_agent_at = now
        self.last_activity_at = now
        if proactive:
            self.proactive_count += 1
            self.last_proactive_at = now
        self.floor_phase = "awaiting_user"

    def bump_poll(self) -> int:
        self.poll_index += 1
        return self.poll_index

    def idle_ms(self, clock: Clock) -> int:
        self.ensure_timeline(clock)
        return max(0, int((clock.now() - self.last_activity_at) * 1000))

    def ms_since_proactive(self, clock: Clock) -> int:
        self.ensure_timeline(clock)
        if self.last_proactive_at <= 0:
            return 10**9
        return max(0, int((clock.now() - self.last_proactive_at) * 1000))

    # --- cast / affect / share ---
    def set_affect(
        self,
        *,
        intensity: float | None = None,
        label: str | None = None,
        valence: str | None = None,
    ) -> None:
        if intensity is not None:
            self.affect.intensity = intensity
        if label is not None:
            self.affect.label = label
        if valence is not None:
            self.affect.valence = valence
        self.affect.clamp()

    def set_agent_status(self, status: str) -> None:
        self.agent_status = status.strip()

    def set_on_scene(self, state: OnSceneState) -> None:
        self.on_scene = state
        self.beats_since_on_scene = 0
        self.on_scene_pending = False

    def mark_on_scene_pending(self) -> None:
        """异步临场任务已踢出；在途期间不再重复踢。"""
        self.on_scene_pending = True

    def mark_rhythm_beat(self) -> None:
        """每次节奏门控拍计数；满 k 后由 rhythm 触发状态刷新。"""
        self.beats_since_on_scene += 1
        self.beats_since_affect += 1

    def mark_affect_refreshed(self) -> None:
        self.beats_since_affect = 0

    def enqueue_share(
        self,
        title: str,
        *,
        detail: str = "",
        urgency: float = 0.0,
    ) -> ShareEvent:
        """urgency 仅兼容外部载荷，不参与任何门控/自动改情感。"""
        event = ShareEvent(title=title.strip(), detail=detail.strip(), urgency=urgency)
        self.share_queue.append(event)
        return event

    def peek_share(self) -> ShareEvent | None:
        if not self.share_queue:
            return None
        return self.share_queue[0]

    def pop_share(self) -> ShareEvent | None:
        if not self.share_queue:
            return None
        event = self.share_queue.pop(0)
        self.last_shared = event
        return event

    def consume_share(self, event_id: str) -> ShareEvent | None:
        """按 id 出队；供 rhythm 消费，避免反复入队。"""
        token = event_id.strip()
        if not token:
            return self.pop_share()
        for idx, event in enumerate(self.share_queue):
            if event.event_id == token:
                taken = self.share_queue.pop(idx)
                self.last_shared = taken
                return taken
        return None

    @property
    def share_pending(self) -> bool:
        return bool(self.share_queue)

    # --- history ---
    def append_user_only(self, user_text: str, *, clock: Clock) -> None:
        """listen/hold：用户话仍入场记，避免下一拍丢失上下文。"""
        body = user_text.strip()
        if not body:
            return
        self.turn_index += 1
        user_ts = self.last_user_at if self.last_user_at > 0 else clock.now()
        self.history.append(HistoryBeat.at("user", body, ts=user_ts))
        if len(self.history) > 24:
            self.history = self.history[-24:]

    def append_turn(self, user_text: str, answer: str, *, clock: Clock) -> None:
        self.turn_index += 1
        agent_ts = clock.now()
        user_ts = self.last_user_at if self.last_user_at > 0 else agent_ts
        if user_text.strip():
            self.history.append(HistoryBeat.at("user", user_text.strip(), ts=user_ts))
        if answer.strip():
            self.history.append(HistoryBeat.at("agent", answer.strip(), ts=agent_ts))
        if len(self.history) > 24:
            self.history = self.history[-24:]

    def recent_beats(self, limit: int = 6) -> tuple[HistoryBeat, ...]:
        return tuple(self.history[-limit:])

    def context_distill(self, *, limit: int = 4) -> str:
        beats = self.history[-limit * 2 :]
        return " | ".join(beat.one_line(limit=40) for beat in beats)

    def working_memory(self, *, limit: int = 4) -> str:
        lines: list[str] = []
        for beat in self.history[-(limit * 2) :]:
            role = "用户" if beat.speaker == "user" else "你"
            lines.append(f"- {role}：{beat.text}")
        return "\n".join(lines)

    # 兼容旧字段名
    @property
    def persona(self) -> str:
        return self.agent_persona

    @property
    def presence(self) -> str:
        return self.agent_presence

    @property
    def portrait(self) -> str:
        return self.cast.user
