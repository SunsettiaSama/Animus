from __future__ import annotations

from delegate.config import DelegateProfile


class DelegateRunner:
    def run_sync(self, instruction: str, profile: DelegateProfile, llm_cfg_path: str) -> str:
        from config.llm_core.config import LLMConfig
        from config.react.tao_config import TaoConfig
        from config.react.prompt_config import PromptConfig
        from llm_core.llm import LLM
        from react.action.manager import ToolManager
        from react.tao import FinishEvent, TaoLoop

        llm = LLM(LLMConfig.from_yaml(llm_cfg_path))

        tool_manager = ToolManager()
        executor = tool_manager.build_executor()
        tool_descriptions = tool_manager.primary_descriptions(profile.tools)
        category_summary = tool_manager.category_summary()

        tao_cfg = TaoConfig(
            max_steps=profile.max_steps,
            memory=profile.memory,
            prompt=PromptConfig(),
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

        answer = ""
        for event in tao.stream(full_instruction):
            if isinstance(event, FinishEvent):
                answer = event.answer
        tao.post_process()
        return answer


# Backward-compatible alias
SubAgentRunner = DelegateRunner
