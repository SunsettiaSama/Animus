from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from infra.agent import AgentService, UserUnit
from infra.agent.ports import ActionRunner
from infra.llm.llm import BaseLLM

from .units import CharacterContextUnit, CharacterHelpObservationUnit

GenerateFn = Callable[[str, str], str]


class _CharacterNoopRunner:
    """角色 agent 不做 T/A/O 工具循环；worker 走 io 分流。"""

    def run(self, calls: list[dict]) -> list[dict]:
        return [
            {
                "tool": str(c.get("action") or ""),
                "observation": "character-agent: tools are routed via speak.io, not prompt actions",
            }
            for c in calls
        ]


@dataclass
class CharacterTurnPacket:
    system: str
    user_text: str
    raw: str
    help_goals: tuple[str, ...] = ()
    help_observations: tuple[str, ...] = ()


class CharacterAgentHost:
    """角色 AgentService：Unit 离散上下文；生成不经工具目录。"""

    def __init__(
        self,
        llm: BaseLLM | None,
        *,
        generate_fn: GenerateFn | None = None,
        action_runner: ActionRunner | None = None,
        name: str = "speak-character",
        auto_start: bool = True,
    ) -> None:
        self._generate_fn = generate_fn
        self._llm = llm
        self._service: AgentService | None = None
        if llm is not None:
            self._service = AgentService(
                llm,
                action_runner or _CharacterNoopRunner(),
                system="你是对话中的角色个体。用交付块开口；具体办事交给后台分流。",
                max_steps=1,
                name=name,
                owner="speak.character",
                auto_start=auto_start,
            )

    @property
    def service(self) -> AgentService | None:
        return self._service

    def stop(self, timeout: float = 30.0) -> None:
        if self._service is not None:
            self._service.stop(timeout=timeout)

    def begin_turn(
        self,
        *,
        system: str,
        user_text: str,
        context_cards: list[tuple[str, str]] | None = None,
        help_observations: tuple[str, ...] = (),
    ) -> None:
        """每轮 reset：过往帧抛弃，只保留当前 Units。"""
        if self._service is None:
            return
        self._service.reset().result(timeout=30.0)
        self._service.set_system(system).result(timeout=30.0)
        for title, body in context_cards or ():
            self._service.inject(CharacterContextUnit(title=title, body=body)).result(timeout=30.0)
        for obs in help_observations:
            if str(obs).strip():
                self._service.inject(
                    CharacterHelpObservationUnit(observation=str(obs).strip())
                ).result(timeout=30.0)
        if user_text.strip():
            self._service.add_user(user_text.strip()).result(timeout=30.0)

    def render_human(self) -> str:
        if self._service is None:
            return ""
        return self._service.timeline.render()

    def generate(
        self,
        *,
        system: str,
        user_text: str,
        context_cards: list[tuple[str, str]] | None = None,
        help_observations: tuple[str, ...] = (),
    ) -> str:
        self.begin_turn(
            system=system,
            user_text=user_text,
            context_cards=context_cards,
            help_observations=help_observations,
        )
        human = self.render_human() or user_text
        if self._generate_fn is not None:
            return self._generate_fn(system, human)
        if self._llm is None:
            raise RuntimeError("CharacterAgentHost has no llm/generate_fn")
        return self._llm.generate(human, system=system).text

    def status(self) -> dict[str, Any]:
        if self._service is None:
            return {"state": "unbound"}
        return self._service.status()
