from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infra.agent import AgentService, Timeline, UserUnit
from infra.agent.ports import ActionRunner
from infra.llm.llm import BaseLLM

from .fate import FateDiceRoll, roll_fate_dice
from .units import FateDiceUnit, MemoryBufferCardUnit, RhythmCardUnit
from ..base import DIRECTOR_VOICE


class _DirectorNoopRunner:
    def run(self, calls: list[dict]) -> list[dict]:
        return [{"tool": str(c.get("action") or ""), "observation": "director-noop"} for c in calls]


@dataclass
class DirectorFrameContext:
    """一帧导演上下文：过往帧抛弃，仅当前 Units。"""

    session_id: str
    rhythm_card: str
    fate: FateDiceRoll
    user_text: str = ""
    signal_summary: str = ""

    def build_timeline(self) -> Timeline:
        timeline = Timeline()
        if self.user_text.strip():
            timeline.inject(UserUnit(text=self.user_text.strip(), source="speak"))
        if self.signal_summary.strip():
            timeline.inject(
                UserUnit(
                    text=self.signal_summary.strip(),
                    source="signals",
                    metadata={"kind": "signal_summary"},
                )
            )
        timeline.inject(RhythmCardUnit(card=self.rhythm_card))
        timeline.inject(
            FateDiceUnit(
                roll=self.fate.roll,
                tendency=self.fate.tendency,
            )
        )
        return timeline

    def render(self) -> str:
        return self.build_timeline().render()


_DIRECTOR_SYSTEM = (
    f"{DIRECTOR_VOICE}\n"
    "根据节奏卡片和命运骰（开口欲的软评分）判断方向。"
    "0 到 10 表示非常不想说话，90 到 100 表示非常想说话；骰只是参考，不直接决定动作。"
    "记忆以离散 unit 的形式存放在共享 buffer 中。可用工具包括："
    "memory_buffer_list、memory_buffer_get、memory_buffer_search"
    "（支持 bm25、embedding 和 hybrid 三种模式）、memory_buffer_inject、memory_buffer_remove。\n"
    "输出文风保持客观、冷静、朴实。不用修辞，不抒情，不说教。"
)


class DirectorAgentHost:
    """注册并拉起导演 AgentService；每帧 reset 后注入卡片 Units。"""

    def __init__(
        self,
        llm: BaseLLM,
        *,
        action_runner: ActionRunner | None = None,
        system: str = "",
        name: str = "speak-director",
        auto_start: bool = True,
    ) -> None:
        self._action_runner = action_runner or _DirectorNoopRunner()
        self._service = AgentService(
            llm,
            self._action_runner,
            system=system or _DIRECTOR_SYSTEM,
            max_steps=2,
            name=name,
            owner="speak.director",
            auto_start=auto_start,
        )

    @property
    def service(self) -> AgentService:
        return self._service

    @property
    def action_runner(self) -> ActionRunner:
        return self._action_runner

    def stop(self, timeout: float = 30.0) -> None:
        self._service.stop(timeout=timeout)

    def begin_frame(
        self,
        *,
        session_id: str,
        rhythm_card: str,
        user_text: str = "",
        signal_summary: str = "",
        previous_fate: int | None = None,
        memory_cards: list[MemoryBufferCardUnit] | None = None,
        rng=None,
    ) -> DirectorFrameContext:
        bind = getattr(self._action_runner, "bind_session", None)
        if callable(bind):
            bind(session_id)
        fate = roll_fate_dice(previous=previous_fate, rng=rng)
        frame = DirectorFrameContext(
            session_id=session_id.strip(),
            rhythm_card=rhythm_card,
            fate=fate,
            user_text=user_text,
            signal_summary=signal_summary,
        )
        self._service.reset().result(timeout=30.0)
        for unit in frame.build_timeline().units:
            self._service.inject(unit).result(timeout=30.0)
        for card in memory_cards or ():
            if card.render().strip():
                self._service.inject(card).result(timeout=30.0)
        return frame

    def render_frame_prompt(self, frame: DirectorFrameContext) -> str:
        return frame.render()

    def status(self) -> dict[str, Any]:
        return self._service.status()
