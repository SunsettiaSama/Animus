from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infra.agent import AgentService, Timeline, UserUnit
from infra.agent.ports import ActionRunner
from infra.llm.llm import BaseLLM

from .fate import FateDiceRoll, roll_fate_dice
from .units import FateDiceUnit, RhythmCardUnit


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
        self._service = AgentService(
            llm,
            action_runner or _DirectorNoopRunner(),
            system=system
            or (
                "你是对话导演。根据节奏卡片与命运骰上下文，决定是否跟随或轻微违背用户节奏；"
                "命运骰只是参考，不直接等于动作。"
            ),
            max_steps=1,
            name=name,
            owner="speak.director",
            auto_start=auto_start,
        )

    @property
    def service(self) -> AgentService:
        return self._service

    def stop(self, timeout: float = 30.0) -> None:
        self._service.stop(timeout=timeout)

    def begin_frame(
        self,
        *,
        session_id: str,
        rhythm_card: str,
        user_text: str = "",
        signal_summary: str = "",
        rng=None,
    ) -> DirectorFrameContext:
        fate = roll_fate_dice(rng=rng)
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
        return frame

    def render_frame_prompt(self, frame: DirectorFrameContext) -> str:
        return frame.render()

    def status(self) -> dict[str, Any]:
        return self._service.status()
