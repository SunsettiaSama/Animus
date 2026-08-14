"""Soul-first bootstrap for WebUI — no TaoLoop / ConvLoop required."""
from __future__ import annotations

import json
import logging
import os
import warnings
from typing import Any

logger = logging.getLogger(__name__)


def load_persona_config_from_state(state: Any):
    """Load PersonaConfig from AppState paths (same fields as react factory)."""
    from config.agent.persona_config import PersonaConfig

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


def build_soul_service(state: Any, *, persona_cfg=None):
    """Construct SoulService from AppState without creating TaoLoop/ConvLoop."""
    from config.infra.db_config import DBConfig
    from config.soul.config import SoulConfig
    from agent.soul import SoulService

    persona = persona_cfg if persona_cfg is not None else load_persona_config_from_state(state)
    if not persona.enabled:
        raise RuntimeError(
            "Soul bootstrap requires persona.enabled=true "
            "(Settings → Persona → 启用人格演化)"
        )

    db_cfg = DBConfig.load_default()
    backend = db_cfg.resolved_storage_backend()
    mysql_client = None
    if backend == "mysql":
        if not db_cfg.mysql.enabled:
            raise RuntimeError(
                "Soul storage backend=mysql，但 MySQL 未启用（config/infra/db.yaml）"
            )
        mysql_client = db_cfg.mysql.build_client()

    llm_handle = None
    if state.llm_service is not None:
        llm_handle = state.llm_service.handle
    if llm_handle is None:
        raise RuntimeError("LLM 未加载，无法启动 Soul")

    return SoulService(
        life_dir=state.cache.life_dir,
        persona_cfg=persona,
        mysql_client=mysql_client,
        llm_service=state.llm_service,
        primary_llm=llm_handle,
        cfg=SoulConfig.load_default(),
        db_cfg=db_cfg,
        storage_backend=backend,
        json_root=db_cfg.storage.json_root,
    )


def do_soul_init(state: Any) -> Any:
    """Start SoulService as the WebUI primary runtime and wire AgentService.

    Returns the running SoulService. Raises on hard failures so the startup
    worker can surface ``state.soul_init_error``.
    """
    from agent.adapters.react_bridge import wire_soul_agent_initiated_notify

    old = getattr(state, "soul_service", None)
    if old is not None and getattr(old, "is_running", False):
        old.stop()

    state.soul_init_error = ""
    soul = build_soul_service(state)
    soul.start()
    state.soul_service = soul

    agent = getattr(state, "agent_service", None)
    if agent is not None:
        agent.set_soul_service(soul)
    wire_soul_agent_initiated_notify(soul, state)

    # Soul-first boot no longer waits on ConvLoop; clear legacy init latch.
    state.react_init_event.set()
    logger.info(
        "[soul_bootstrap] Soul started  speak_initialized=%s state=%s",
        getattr(soul, "speak_initialized", False),
        soul.state,
    )
    print(
        f"[webui] Soul started  speak_initialized={getattr(soul, 'speak_initialized', False)}"
    )
    return soul


def warn_legacy_react(feature: str) -> None:
    """Emit a one-line deprecation warning for legacy ReAct/TaoLoop paths."""
    warnings.warn(
        f"Legacy ReAct/TaoLoop path used for {feature!r}; "
        "WebUI primary runtime is Soul/Speak. Prefer /ws/speak/run.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning(
        "[deprecated] Legacy ReAct/TaoLoop path used for %r — "
        "primary runtime is Soul/Speak",
        feature,
    )
