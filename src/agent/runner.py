from __future__ import annotations

from agent.profile import SubAgentProfile


class SubAgentRunner:
    def run_sync(
        self,
        instruction: str,
        profile: SubAgentProfile,
        llm_cfg_path: str,
        event_callback=None,
    ) -> dict:
        from config.llm_core.config import LLMConfig
        from config.agent.tao_config import TaoConfig
        from config.agent.prompt_config import PromptConfig
        from infra.llm import LLM
        from agent.react.action.manager import ToolManager
        from agent.react.tao import FinishEvent, StepEvent, TaoLoop

        llm = LLM(LLMConfig.from_yaml(llm_cfg_path))

        tool_manager = ToolManager()
        executor = tool_manager.build_executor()
        tool_descriptions = tool_manager.primary_descriptions(profile.tools)
        category_summary = tool_manager.category_summary()

        tao_cfg = TaoConfig(
            max_steps=profile.max_steps,
            memory=profile.memory,
            prompt=PromptConfig(),
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
            if event_callback is not None:
                event_callback(event)
            if isinstance(event, StepEvent):
                obs_preview = event.observation[:200] if event.observation else ""
                steps_log.append(f"[{event.action}] {obs_preview}")
            if isinstance(event, FinishEvent):
                answer = event.answer
        tao.post_process()

        return {
            "answer": answer,
            "step_count": len(steps_log),
            "steps_log": steps_log,
        }
