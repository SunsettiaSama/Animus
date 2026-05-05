from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ...action.skill.base import BaseSkill


class DelegateTaskArgs(BaseModel):
    instruction: str = Field(..., min_length=1, description="交给子 Agent 执行的完整指令")
    profile: str = Field(
        "minimal",
        description=(
            "子 Agent 能力配置：minimal（默认，通用）| executor（执行型）| "
            "researcher（研究/搜索）| researcher_with_memory（研究+长期记忆）| "
            "analyst（分析/计算）"
        ),
    )


class DelegateTaskSkill(BaseSkill):
    name: str = "delegate_task"
    description: str = (
        "将一个具体任务委派给子 Agent 同步执行，等待完成后返回结果。"
        "适合需要即时结果的单次委派。"
        "参数：instruction（给子 Agent 的完整指令），"
        "profile（minimal|executor|researcher|researcher_with_memory|analyst，默认 minimal）。"
    )
    skill_type: str = "simple"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = DelegateTaskArgs

    runner: Any = None        # SubAgentRunner，由 TaoLoop 注入
    cfg: Any = None           # SubAgentConfig，由 TaoLoop 注入
    sub_event_sink: Any = None  # Callable[[TaoEvent], None] | None，由 TaoLoop.sub_event_sink setter 注入

    def _forward(self, event) -> None:
        if self.sub_event_sink is None:
            return
        from agent.react.tao import (
            ChunkEvent, StepEvent, FinishEvent,
            SubAgentChunkEvent, SubAgentStepEvent, SubAgentFinishEvent,
        )
        if isinstance(event, ChunkEvent):
            self.sub_event_sink(SubAgentChunkEvent(index=event.index, chunk=event.chunk))
        elif isinstance(event, StepEvent):
            is_err = event.observation.startswith("[工具执行错误]")
            self.sub_event_sink(SubAgentStepEvent(
                index=event.index,
                thought=event.thought,
                action=event.action,
                action_input=event.action_input,
                observation=event.observation,
                is_error=is_err,
            ))
        elif isinstance(event, FinishEvent):
            self.sub_event_sink(SubAgentFinishEvent(answer=event.answer))

    def execute(self, instruction: str, profile: str = "minimal", **kwargs) -> str:
        from agent.profile import SubAgentProfile
        from agent.react.tao import SubAgentStartEvent, SubAgentErrorEvent
        if self.runner is None or self.cfg is None:
            return "DelegateTaskSkill 未正确初始化（runner 或 cfg 为 None）。"
        profile_obj = self.cfg.profiles.get(profile) or SubAgentProfile()
        if self.sub_event_sink is not None:
            self.sub_event_sink(SubAgentStartEvent(action=self.name, instruction=instruction))
        try:
            result = self.runner.run_sync(
                instruction, profile_obj, self.cfg.llm_cfg_path,
                event_callback=self._forward,
            )
        except Exception as exc:
            if self.sub_event_sink is not None:
                self.sub_event_sink(SubAgentErrorEvent(error=str(exc)))
            raise
        return result.get("answer", "")
