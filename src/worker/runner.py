from __future__ import annotations

import copy
import os

from worker.profile import SubAgentProfile


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
    lt = memory_cfg.long_term
    model_path = emb.model_name_or_path
    if model_path and not os.path.isabs(model_path):
        resolved = str(paths.root / model_path)
        if os.path.isdir(resolved):
            model_path = resolved
    lt.model_name_or_path = model_path
    lt.use_fp16 = emb.use_fp16
    lt.device = emb.device
    lt.query_prefix = emb.query_prefix
    lt.passage_prefix = emb.passage_prefix
    return memory_cfg


class SubAgentRunner:
    def run_sync(
        self,
        instruction: str,
        profile: SubAgentProfile | None = None,
        llm_cfg_path: str = "",
        event_callback=None,
        notify_fn=None,
        reply_target=None,
        scheduler_engine=None,
        comm_rate_cfg=None,
        soul=None,
        agent_state_service=None,
        sandbox=None,
        risk_gate=None,
        tao_holder=None,
        on_tao_ready=None,
        card_id: str | None = None,
    ) -> dict:
        from config.llm_core.config import LLMConfig
        from config.agent.tao_config import TaoConfig
        from config.agent.prompt_config import PromptConfig
        from infra.llm import LLM
        from worker.cards import materialize_capability
        from worker.tools.manager import ToolManager
        from worker.engine.tao import FinishEvent, StepEvent, TaoLoop

        if profile is None:
            if not card_id:
                raise ValueError("SubAgentRunner requires profile or card_id")
            profile = materialize_capability(card_id)
        elif card_id:
            # Explicit profile wins; card_id ignored when profile provided.
            pass

        llm = LLM(LLMConfig.from_yaml(llm_cfg_path))

        tool_manager = ToolManager()

        raw_tools: str | list[str] | None = profile.tool_package or profile.tools
        if profile.tool_package and profile.tools:
            pkg_tools = tool_manager.resolve_tools(profile.tool_package) or []
            raw_tools = pkg_tools + [t for t in profile.tools if t not in pkg_tools]

        # Prompt stays lean: primary + lookups only.
        prompt_names = tool_manager.prompt_tool_names()
        tool_descriptions = tool_manager.primary_descriptions(prompt_names)
        # Executor allow-list: package tools + lookups + latent shell runners.
        allowed = tool_manager.resolve_allowed_actions(raw_tools)
        executor = tool_manager.build_executor(allowed_actions=allowed)

        # Soul tools remain callable via allow-list / register_instance, but are
        # not dumped into the prompt tool_list (lookup-first policy).
        if soul is not None and profile.tools:
            from agent.adapters.soul_tao.tools import merge_profile_soul_tool_descriptions

            # Keep soul tools on allow-list without expanding prompt descriptions.
            for name in profile.tools:
                if name.startswith("soul_") and name not in allowed:
                    allowed.append(name)
            executor.restrict_to(set(allowed))
            _ = merge_profile_soul_tool_descriptions

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
            sandbox=sandbox,
            risk_gate=risk_gate,
            notify_fn=notify_fn,
            reply_target=reply_target,
            scheduler_engine=scheduler_engine,
            comm_rate_cfg=comm_rate_cfg,
            soul_service=soul,
            agent_state_service=agent_state_service,
            prompt_tool_names=set(prompt_names),
        )
        if tao_holder is not None:
            tao_holder["tao"] = tao
        if on_tao_ready is not None:
            on_tao_ready(tao)

        full_instruction = (
            f"{profile.system_note}\n\n{instruction}" if profile.system_note else instruction
        )

        steps_log: list[str] = []
        steps: list[dict] = []
        answer = ""
        for event in tao.stream(full_instruction):
            if event_callback is not None:
                event_callback(event)
            if isinstance(event, StepEvent):
                obs_preview = event.observation[:200] if event.observation else ""
                steps_log.append(f"[{event.action}] {obs_preview}")
                steps.append({
                    "index": event.index,
                    "thought": event.thought,
                    "action": event.action,
                    "action_input": event.action_input,
                    "observation": event.observation,
                })
            if isinstance(event, FinishEvent):
                answer = event.answer

        # Worker owns post_process + portraits; do not record as Soul dialogue.
        tao.post_process()

        return {
            "answer": answer,
            "step_count": len(steps),
            "steps_log": steps_log,
            "steps": steps,
            "units": [
                u.to_dict()
                for u in (
                    tao.context_timeline.units if tao.context_timeline is not None else ()
                )
            ],
        }
