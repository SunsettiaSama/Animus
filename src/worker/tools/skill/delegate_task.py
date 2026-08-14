from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from .base import BaseSkill


class DelegateTaskArgs(BaseModel):
    instruction: str = Field(..., min_length=1, description="交给子 Agent 执行的完整指令")
    card: str = Field(
        "minimal",
        description=(
            "Capability card id：minimal|executor|researcher|researcher_with_memory|"
            "analyst|coder 或 package 薄卡"
        ),
    )


class DelegateTaskSkill(BaseSkill):
    name: str = "delegate_task"
    description: str = (
        "将一个具体任务委派给子 Agent 同步执行，等待完成后返回结果。"
        "适合需要即时结果的单次委派。"
        "参数：instruction（给子 Agent 的完整指令），"
        "card（capability card id，默认 minimal）。"
    )
    skill_type: str = "simple"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = DelegateTaskArgs

    runner: Any = None
    cfg: Any = None
    sub_event_sink: Any = None
    agent_state_service: Any = None

    def _forward(self, event) -> None:
        if self.sub_event_sink is None:
            return
        from worker.engine.tao import (
            ChunkEvent,
            StepEvent,
            FinishEvent,
            SubAgentChunkEvent,
            SubAgentStepEvent,
            SubAgentFinishEvent,
        )

        if isinstance(event, ChunkEvent):
            self.sub_event_sink(SubAgentChunkEvent(index=event.index, chunk=event.chunk))
        elif isinstance(event, StepEvent):
            is_err = event.observation.startswith("[工具执行错误]")
            self.sub_event_sink(
                SubAgentStepEvent(
                    index=event.index,
                    thought=event.thought,
                    action=event.action,
                    action_input=event.action_input,
                    observation=event.observation,
                    is_error=is_err,
                )
            )
        elif isinstance(event, FinishEvent):
            self.sub_event_sink(SubAgentFinishEvent(answer=event.answer))

    def execute(self, instruction: str, card: str = "minimal", **kwargs) -> str:
        from worker.cards import materialize_capability

        if self.runner is None or self.cfg is None:
            raise RuntimeError("DelegateTaskSkill 未正确初始化（runner 或 cfg 为 None）")
        profile_obj = materialize_capability(card)
        if self.sub_event_sink is not None:
            from worker.engine.tao import SubAgentStartEvent

            self.sub_event_sink(SubAgentStartEvent(action=self.name, instruction=instruction))
        result = self.runner.run_sync(
            instruction,
            profile_obj,
            self.cfg.llm_cfg_path,
            event_callback=self._forward,
            agent_state_service=self.agent_state_service,
            card_id=card,
        )
        return result.get("answer", "")
