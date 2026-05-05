from __future__ import annotations

import uuid

from crew.config import CrewConfig, CrewProfile, flatten_recursive
from crew.result import CrewResult


class CrewRunner:
    def run_sync(
        self,
        instruction: str,
        profile: CrewProfile,
        llm_cfg_path: str,
        crew_cfg: CrewConfig | None = None,
    ) -> CrewResult:
        from config.llm_core.config import LLMConfig
        from config.react.tao_config import TaoConfig
        from config.react.prompt_config import PromptConfig
        from llm_core.llm import LLM
        from react.action.manager import ToolManager
        from react.tao import FinishEvent, StepEvent, TaoLoop

        llm = LLM(LLMConfig.from_yaml(llm_cfg_path))

        tool_manager = ToolManager()
        executor = tool_manager.build_executor()
        tool_descriptions = tool_manager.primary_descriptions(profile.tools)
        category_summary = tool_manager.category_summary()

        child_crew_cfg = None
        if profile.recursive and crew_cfg is not None:
            child_crew_cfg = flatten_recursive(crew_cfg)

        tao_cfg = TaoConfig(
            max_steps=profile.max_steps,
            memory=profile.memory,
            prompt=PromptConfig(),
            crew=child_crew_cfg,
            scheduler=None,
        )

        tao = TaoLoop(
            llm=llm,
            executor=executor,
            tool_descriptions=tool_descriptions,
            cfg=tao_cfg,
            tool_category_summary=category_summary,
        )

        full_instruction = (
            f"{profile.system_note}\n\n{instruction}" if profile.system_note else instruction
        )

        steps_log: list[str] = []
        answer = ""
        for event in tao.stream(full_instruction):
            if isinstance(event, StepEvent):
                obs_preview = event.observation[:200] if event.observation else ""
                steps_log.append(f"[{event.action}] {obs_preview}")
            if isinstance(event, FinishEvent):
                answer = event.answer
        tao.post_process()

        return CrewResult(
            agent_id=str(uuid.uuid4()),
            status="done",
            answer=answer,
            log=steps_log,
        )
