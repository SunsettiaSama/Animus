from __future__ import annotations

import os
from typing import Any


def build_conv_loop(
    state: Any,
    lang: str = "cn",
    max_steps: int = 10,
    primary_tools: list[str] | None = None,
    enable_kb: bool = False,
    scheduler_engine: Any = None,
    reply_target: dict | None = None,
) -> Any:
    """Create a fresh ConvLoop (wrapping a new TaoLoop) from AppState.

    Extracted from ``agent.adapters.react_bridge.do_react_init`` so that both the WebUI
    router and the BotService can create independent per-session ConvLoops
    without duplicating configuration logic.

    Returns the ``ConvLoop`` instance only; callers that also need the
    underlying ``TaoLoop`` (e.g. for scheduler or preload) should access
    ``conv_loop._tao`` directly.
    """
    from config.agent.tao_config import TaoConfig
    from config.agent.prompt_config import PromptConfig
    from config.agent.memory.memory_config import MemoryConfig
    from config.agent.persona_config import PersonaConfig
    from runtime.scheduler import SchedulerConfig
    from agent.profile import SubAgentConfig
    from agent.react.loop import ConvLoop
    from agent.react.tao import TaoLoop
    from config.agent.risk_config import RiskConfig
    from agent.react.action.risk.gate import RiskGate
    from agent.flow.cluster.config import FlowConfig

    def _load_memory_config() -> MemoryConfig:
        from agent.runner import _apply_embedding_override

        memory = (
            MemoryConfig.from_yaml(state.memory_config_yaml)
            if os.path.exists(state.memory_config_yaml)
            else MemoryConfig()
        )
        return _apply_embedding_override(memory)

    def _load_persona_config() -> PersonaConfig:
        import json
        d: dict = {}
        if os.path.exists(state.persona_cfg_file):
            with open(state.persona_cfg_file, encoding="utf-8") as fh:
                d = json.load(fh)
        return PersonaConfig(
            enabled=d.get("enabled", False),
            persona_dir=state.persona_dir,
            expectation_tier_override=str(d.get("expectation_tier_override", "中")),
            max_profile_chars=d.get("max_profile_chars", 500),
            evolution_enabled=d.get("evolution_enabled", False),
            evolve_interval=d.get("evolve_interval", 1),
            skills_enabled=d.get("skills_enabled", True),
            max_skills_in_prompt=d.get("max_skills_in_prompt", 5),
            max_skills_chars=d.get("max_skills_chars", 600),
            reflection_enabled=d.get("reflection_enabled", False),
            reflect_interval=d.get("reflect_interval", 3),
            max_reflection_chars=d.get("max_reflection_chars", 400),
        )

    executor          = state.tool_manager.build_executor()
    tool_descriptions = state.tool_manager.primary_descriptions(primary_tools)
    category_summary  = state.tool_manager.category_summary()

    persona_cfg = _load_persona_config()
    db_cfg = None
    if persona_cfg.enabled:
        from config.infra.db_config import DBConfig
        db_cfg = DBConfig.load_default()

    cfg = TaoConfig(
        max_steps=max_steps,
        storage=state.cache,
        prompt=PromptConfig(lang=lang),
        memory=_load_memory_config(),
        persona=persona_cfg,
        knowledge=state.kb_cfg if enable_kb else None,
        scheduler=SchedulerConfig(
            scheduler_dir=state.cache.scheduler_dir,
            llm_cfg_path=state.llm_config_yaml,
        ),
        agent=SubAgentConfig(llm_cfg_path=state.llm_config_yaml),
        flow=FlowConfig(),
        db=db_cfg,
    )

    # Prefer the caller-supplied global engine; fall back to per-loop creation via cfg.scheduler.
    _sched_engine = scheduler_engine if scheduler_engine is not None else getattr(state, "scheduler_engine", None)

    risk_gate = RiskGate.from_config(RiskConfig())
    tao = TaoLoop(
        llm=state.llm_service.handle,
        executor=executor,
        tool_descriptions=tool_descriptions,
        cfg=cfg,
        tool_category_summary=category_summary,
        sandbox=state.sandbox_manager,
        risk_gate=risk_gate,
        scheduler_engine=_sched_engine,
        reply_target=reply_target,
        llm_service=state.llm_service,
    )
    return ConvLoop(tao)
