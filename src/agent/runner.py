from __future__ import annotations

import copy
import os

from agent.profile import SubAgentProfile


def _apply_embedding_override(memory_cfg):
    """Apply config/embedding/model.yaml override to a MemoryConfig instance.

    Mirrors the logic in AppConfig.from_disk() and factory.build_conv_loop(),
    ensuring the local model path is used instead of the Hub ID default.
    """
    from config import paths
    from config.agent.memory.embedding_config import EmbeddingConfig

    if not paths.embedding_model_yaml.exists():
        return memory_cfg
    emb = EmbeddingConfig.from_yaml(str(paths.embedding_model_yaml))
    lt  = memory_cfg.long_term
    model_path = emb.model_name_or_path
    if model_path and not os.path.isabs(model_path):
        resolved = str(paths.root / model_path)
        if os.path.isdir(resolved):
            model_path = resolved
    lt.model_name_or_path = model_path
    lt.use_fp16           = emb.use_fp16
    lt.device             = emb.device
    lt.query_prefix       = emb.query_prefix
    lt.passage_prefix     = emb.passage_prefix
    return memory_cfg


class SubAgentRunner:
    def run_sync(
        self,
        instruction: str,
        profile: SubAgentProfile,
        llm_cfg_path: str,
        event_callback=None,
        notify_fn=None,
        reply_target=None,
        scheduler_engine=None,
        comm_rate_cfg=None,
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
            memory=_apply_embedding_override(copy.deepcopy(profile.memory)),
            prompt=PromptConfig(),
            scheduler=None,
        )

        tao = TaoLoop(
            llm=llm,
            executor=executor,
            tool_descriptions=tool_descriptions,
            cfg=tao_cfg,
            tool_category_summary=category_summary,
            notify_fn=notify_fn,
            reply_target=reply_target,
            scheduler_engine=scheduler_engine,
            comm_rate_cfg=comm_rate_cfg,
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
