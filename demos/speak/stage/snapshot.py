from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..contracts import Clock
from .desire import DesireArc
from .director_log import DirectorBeat, weave_dialogue_and_directors
from .floor import FloorPhase, floor_nl
from .models import AffectState, CastPortraits, HistoryBeat, ShareEvent, StageState
from .on_scene import OnSceneState
from .review import RhythmReview, review_abstract_block, streak_warning_block

TurnTrigger = Literal["user", "poll"]


def _affect_nl(label: str, valence: str) -> str:
    label = label.strip() or "（未标注）"
    valence = valence.strip()
    if not valence or valence == "neutral":
        return label
    return f"{label}；倾向 {valence}"


def _idle_nl(idle_ms: int) -> str:
    sec = max(0.0, idle_ms / 1000.0)
    return f"空闲约 {sec:.1f} 秒（体感参考，勿套阈值）"


def _since_proactive_nl(ms: int, *, proactive_count: int) -> str:
    if proactive_count <= 0 or ms >= 10**8:
        return "本轮还没有主动开过口"
    sec = max(0.0, ms / 1000.0)
    return f"距上次主动开口约 {sec:.1f} 秒；本轮已主动 {proactive_count} 次"


def resolve_floor_phase(
    stage: StageState,
    *,
    clock: Clock,
    trigger: TurnTrigger,
) -> FloorPhase:
    """吐字中优先；用户拍清场；否则保留 awaiting_user。"""
    del clock
    if stage.floor_phase == "typing":
        return "typing"
    if trigger == "user":
        return "clear"
    if stage.floor_phase == "awaiting_user":
        return "awaiting_user"
    return "clear"


@dataclass(frozen=True)
class StageSnapshot:
    """会话快照：开口指令中枢每拍看到的材料。"""

    session_id: str
    turn_index: int
    trigger: TurnTrigger
    user_text: str
    idle_ms: int
    poll_index: int
    proactive_count: int
    ms_since_proactive: int
    silence_armed: bool
    push_phase: str
    share_queue: tuple[ShareEvent, ...]
    affect: AffectState
    cast: CastPortraits
    history: tuple[HistoryBeat, ...]
    agent_status: str
    desire_arc: DesireArc | None = None
    rhythm_review: RhythmReview | None = None
    context_distill: str = ""
    floor_phase: FloorPhase = "clear"
    director_beats: tuple[DirectorBeat, ...] = ()
    last_shared: ShareEvent | None = None
    on_scene: OnSceneState | None = None
    last_gate: str = ""
    gate_streak: int = 0

    @property
    def share_pending(self) -> bool:
        return bool(self.share_queue)

    @property
    def share_wants(self) -> bool:
        return self.share_pending

    def prompt_lines(self) -> str:
        lines = [
            "# 会话快照",
            f"session={self.session_id} turn={self.turn_index} trigger={self.trigger}",
            f"poll_index={self.poll_index}",
            "",
            "## 台面状态",
            floor_nl(self.floor_phase, idle_ms=self.idle_ms),
            "",
            "## 时间体感（仅供感受，勿套阈值）",
            _idle_nl(self.idle_ms),
            _since_proactive_nl(
                self.ms_since_proactive,
                proactive_count=self.proactive_count,
            ),
            f"本轮已主动开口 {self.proactive_count} 次",
            "",
            "## 角色卡",
            f"agent: {self.cast.agent}",
            f"user: {self.cast.user}",
            "",
            "## Agent 当下",
            self.agent_status.strip() or "（无）",
            "",
            "## 临场状态（rhythm 单独轮询；勿当台词念）",
        ]
        if self.on_scene is None or not self.on_scene.ready:
            lines.append("（未刷新）")
        else:
            lines.append(
                f"[{self.on_scene.focus}] {self.on_scene.text.strip()}"
            )
        lines.extend(
            [
                "",
                "## 情感（应随对话变，不是固定贴纸）",
                _affect_nl(self.affect.label, self.affect.valence),
                "",
                "## 对话弧（当前基调；旧弧已丢弃）",
            ]
        )
        if self.desire_arc is None:
            lines.append("（未 init）")
        else:
            lines.append(self.desire_arc.text.strip() or "（空）")
        lines.extend(review_abstract_block(self.rhythm_review))
        lines.extend(streak_warning_block(self.last_gate, self.gate_streak))
        lines.extend(["", "## 待分享队列（外部注入；分享时用 share_id 点名）"])
        if not self.share_queue:
            lines.append("（空）")
        else:
            for idx, event in enumerate(self.share_queue[:5], start=1):
                lines.append(f"{idx}. id={event.event_id} {event.one_line()}")
        lines.extend(["", "## 可展开分享（上一拍已出队；poll 可 share_tag=expand）"])
        if self.last_shared is None:
            lines.append("（无）")
        else:
            lines.append(
                f"id={self.last_shared.event_id} {self.last_shared.one_line()}"
            )
        lines.extend(
            [
                "",
                "## 场记轨迹（对白为主；仅附带近期真正开口过的导演决策，listen/hold 不回灌）",
            ]
        )
        lines.extend(
            weave_dialogue_and_directors(
                self.history,
                self.director_beats,
                history_limit=6,
                director_limit=2,
            )
        )
        if self.user_text.strip():
            lines.extend(["", "## 本拍用户说", self.user_text.strip()[:400]])
        elif self.trigger == "poll":
            lines.extend(["", "## 本拍", "（空闲轮询：无用户新话）"])
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "trigger": self.trigger,
            "user_text": self.user_text,
            "idle_ms": self.idle_ms,
            "poll_index": self.poll_index,
            "floor_phase": self.floor_phase,
            "share_queue": [item.snapshot() for item in self.share_queue],
            "affect": self.affect.snapshot(),
            "cast": self.cast.snapshot(),
            "agent_status": self.agent_status,
            "desire_arc": None if self.desire_arc is None else self.desire_arc.snapshot(),
            "rhythm_review": None
            if self.rhythm_review is None
            else self.rhythm_review.snapshot(),
            "gate_streak": self.gate_streak,
            "last_gate": self.last_gate,
            "director_beats": [b.snapshot() for b in self.director_beats[-2:]],
            "last_shared": None if self.last_shared is None else self.last_shared.snapshot(),
            "on_scene": None if self.on_scene is None else self.on_scene.snapshot(),
            "history": [beat.meta_snapshot() for beat in self.history[-8:]],
        }


def capture_stage(
    stage: StageState,
    user_text: str,
    *,
    clock: Clock,
    trigger: TurnTrigger,
    push_phase: str = "idle",
    poll_index: int | None = None,
) -> StageSnapshot:
    stage.ensure_timeline(clock)
    floor = resolve_floor_phase(stage, clock=clock, trigger=trigger)
    return StageSnapshot(
        session_id=stage.session_id,
        turn_index=stage.turn_index + 1,
        trigger=trigger,
        user_text=user_text.strip(),
        idle_ms=stage.idle_ms(clock),
        poll_index=stage.poll_index if poll_index is None else poll_index,
        proactive_count=stage.proactive_count,
        ms_since_proactive=stage.ms_since_proactive(clock),
        silence_armed=stage.silence_armed,
        push_phase=push_phase,
        share_queue=tuple(stage.share_queue),
        affect=AffectState(
            intensity=stage.affect.intensity,
            label=stage.affect.label,
            valence=stage.affect.valence,
        ),
        cast=CastPortraits(agent=stage.cast.agent, user=stage.cast.user),
        history=stage.recent_beats(8),
        agent_status=stage.agent_status,
        desire_arc=stage.desire_arc,
        rhythm_review=stage.rhythm_review,
        context_distill=stage.context_distill(),
        floor_phase=floor,
        director_beats=stage.recent_directors(2),
        last_shared=stage.last_shared,
        on_scene=OnSceneState(
            text=stage.on_scene.text,
            focus=stage.on_scene.focus,
            beat_index=stage.on_scene.beat_index,
        ),
        last_gate=stage.last_gate,
        gate_streak=stage.gate_streak,
    )
