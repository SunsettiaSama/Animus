from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .contracts import OnSceneState, RhythmAffect, ShareItem
from .state import (
    DirectorLogBeat,
    HistoryBeat,
    RhythmSessionState,
    gate_streak_warning,
)

RhythmTrigger = Literal["inbound", "proactive"]


@dataclass(frozen=True)
class RhythmSnapshot:
    session_id: str
    turn_index: int
    trigger: RhythmTrigger
    user_text: str
    beat_index: int
    arc_text: str
    review_abstract: str
    affect: RhythmAffect
    on_scene: OnSceneState
    history: tuple[HistoryBeat, ...]
    director_log: tuple[DirectorLogBeat, ...]
    share_queue: tuple[ShareItem, ...]
    last_shared: ShareItem | None
    typing_active: bool = False
    typing_idle: bool = True
    push_phase: str = "idle"
    brew_queue_depth: int = 0
    last_gate: str = ""
    gate_streak: int = 0
    working_memory: str = ""
    context_distill: str = ""

    def prompt_lines(self) -> str:
        lines = [
            "# 会话快照",
            f"session={self.session_id} turn={self.turn_index} trigger={self.trigger}",
            f"beat_index={self.beat_index}",
            "",
            "## 台面状态",
            (
                f"push_phase={self.push_phase} typing_active={self.typing_active} "
                f"typing_idle={self.typing_idle} brew_queue_depth={self.brew_queue_depth}"
            ),
            "",
            "## 情感（应随对话变，不是固定贴纸）",
            (
                f"{self.affect.label}"
                if self.affect.valence == "neutral"
                else f"{self.affect.label}；倾向 {self.affect.valence}"
            ),
            "",
            "## 临场状态（勿当台词念）",
        ]
        if not self.on_scene.ready:
            lines.append("（未刷新）")
        else:
            lines.append(f"[{self.on_scene.focus}] {self.on_scene.text.strip()}")
        lines.extend(["", "## 对话弧（当前基调）"])
        lines.append(self.arc_text.strip() or "（未 init）")
        if self.review_abstract.strip():
            lines.extend(
                [
                    "",
                    "## 复盘原则（伪学习 abstract）",
                    self.review_abstract.strip(),
                ]
            )
        warning = gate_streak_warning(self.last_gate, self.gate_streak)
        if warning:
            lines.extend(["", "## 连续指令警示", warning])
        lines.extend(["", "## 待分享队列（分享时用 share_id 点名）"])
        if not self.share_queue:
            lines.append("（空）")
        else:
            for idx, item in enumerate(self.share_queue[:5], start=1):
                lines.append(f"{idx}. id={item.item_id} {item.one_line()}")
        lines.extend(["", "## 可展开分享（上一拍已出队；可 share_tag=expand）"])
        if self.last_shared is None:
            lines.append("（无）")
        else:
            lines.append(
                f"id={self.last_shared.item_id} {self.last_shared.one_line()}"
            )
        if self.working_memory.strip() or self.context_distill.strip():
            lines.extend(["", "## 工作记忆 / 蒸馏"])
            if self.working_memory.strip():
                lines.append(self.working_memory.strip()[:400])
            if self.context_distill.strip():
                lines.append(self.context_distill.strip()[:400])
        lines.extend(["", "## 场记轨迹（对白为主）"])
        if not self.history:
            lines.append("（尚无对白）")
        else:
            for beat in self.history[-6:]:
                lines.append(f"- {beat.one_line()}")
        recent_directors = [
            beat for beat in self.director_log[-2:] if beat.spoke or beat.gate in ("speak", "brew")
        ]
        if recent_directors:
            lines.extend(["", "## 近期开口导演决策"])
            for beat in recent_directors:
                lines.append(f"- {beat.one_line()}")
        if self.user_text.strip():
            lines.extend(["", "## 本拍用户说", self.user_text.strip()[:400]])
        elif self.trigger == "proactive":
            lines.extend(["", "## 本拍", "（主动/空闲：无用户新话）"])
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "trigger": self.trigger,
            "user_text": self.user_text,
            "beat_index": self.beat_index,
            "arc_text": self.arc_text,
            "review_abstract": self.review_abstract,
            "affect": self.affect.snapshot(),
            "on_scene": self.on_scene.snapshot(),
            "history": [item.snapshot() for item in self.history],
            "share_queue": [item.snapshot() for item in self.share_queue],
            "last_shared": None
            if self.last_shared is None
            else self.last_shared.snapshot(),
            "typing_active": self.typing_active,
            "typing_idle": self.typing_idle,
            "push_phase": self.push_phase,
            "brew_queue_depth": self.brew_queue_depth,
            "last_gate": self.last_gate,
            "gate_streak": self.gate_streak,
        }


def build_rhythm_snapshot(
    state: RhythmSessionState,
    *,
    user_text: str,
    trigger: RhythmTrigger,
    turn_index: int,
    share_queue: tuple[ShareItem, ...] = (),
    typing_active: bool = False,
    typing_idle: bool = True,
    push_phase: str = "idle",
    brew_queue_depth: int = 0,
    working_memory: str = "",
    context_distill: str = "",
) -> RhythmSnapshot:
    return RhythmSnapshot(
        session_id=state.session_id,
        turn_index=turn_index,
        trigger=trigger,
        user_text=user_text.strip(),
        beat_index=state.beat_index,
        arc_text=state.arc_text,
        review_abstract=state.review.abstract,
        affect=RhythmAffect(
            label=state.affect.label,
            valence=state.affect.valence,
            intensity=state.affect.intensity,
        ),
        on_scene=OnSceneState(
            text=state.on_scene.text,
            focus=state.on_scene.focus,
            beat_index=state.on_scene.beat_index,
        ),
        history=state.recent_history(8),
        director_log=state.recent_directors(6),
        share_queue=share_queue,
        last_shared=state.last_shared,
        typing_active=typing_active,
        typing_idle=typing_idle,
        push_phase=push_phase,
        brew_queue_depth=brew_queue_depth,
        last_gate=state.last_gate,
        gate_streak=state.gate_streak,
        working_memory=working_memory,
        context_distill=context_distill,
    )
