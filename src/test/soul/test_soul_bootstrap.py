"""Soul-first bootstrap: no TaoLoop/ConvLoop required for WebUI primary runtime."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.adapters.soul_bootstrap import (
    build_soul_service,
    load_persona_config_from_state,
    warn_legacy_react,
)
from config.agent.persona_config import PersonaConfig


def test_load_persona_config_from_state(tmp_path):
    persona_file = tmp_path / "persona_config.json"
    persona_file.write_text(
        '{"enabled": true, "expectation_tier_override": "高"}',
        encoding="utf-8",
    )
    state = SimpleNamespace(
        persona_cfg_file=str(persona_file),
        persona_dir=str(tmp_path / "persona"),
    )
    cfg = load_persona_config_from_state(state)
    assert cfg.enabled is True
    assert cfg.expectation_tier_override == "高"


def test_build_soul_service_requires_persona_enabled(tmp_path):
    state = SimpleNamespace(
        persona_cfg_file=str(tmp_path / "missing.json"),
        persona_dir=str(tmp_path / "persona"),
        llm_service=SimpleNamespace(handle=object()),
        cache=SimpleNamespace(life_dir=str(tmp_path / "life")),
    )
    with pytest.raises(RuntimeError, match="persona.enabled=true"):
        build_soul_service(
            state,
            persona_cfg=PersonaConfig(enabled=False, persona_dir=str(tmp_path / "persona")),
        )


def test_build_soul_service_requires_llm(tmp_path):
    state = SimpleNamespace(
        persona_cfg_file=str(tmp_path / "missing.json"),
        persona_dir=str(tmp_path / "persona"),
        llm_service=SimpleNamespace(handle=None),
        cache=SimpleNamespace(life_dir=str(tmp_path / "life")),
    )
    with pytest.raises(RuntimeError, match="LLM 未加载"):
        build_soul_service(
            state,
            persona_cfg=PersonaConfig(enabled=True, persona_dir=str(tmp_path / "persona")),
        )


def test_warn_legacy_react_emits_warning():
    with pytest.warns(DeprecationWarning, match="Legacy ReAct"):
        warn_legacy_react("/api/react/init")
