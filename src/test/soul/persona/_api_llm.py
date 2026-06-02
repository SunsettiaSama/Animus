from __future__ import annotations

import os
from pathlib import Path

import pytest

from config.llm_core.config import LLMConfig
from infra.llm import LLM

_ROOT = Path(__file__).resolve().parents[4]


def _llm_yaml_candidates() -> list[Path]:
    return [
        _ROOT / "config" / "llm_core" / "config.yaml",
        _ROOT / "config" / "llm.yaml",
        _ROOT / "config" / "llm_core.yaml",
    ]


def _load_llm_config() -> LLMConfig:
    api_key = os.environ.get("REACT_TEST_LLM_API_KEY", "").strip()
    model = os.environ.get("REACT_TEST_LLM_MODEL", "").strip()
    base_url = os.environ.get("REACT_TEST_LLM_BASE_URL", "").strip() or None
    if api_key and model:
        return LLMConfig(
            backend="openai",
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=int(os.environ.get("REACT_TEST_LLM_MAX_TOKENS", "1024")),
            temperature=float(os.environ.get("REACT_TEST_LLM_TEMPERATURE", "0.3")),
        )
    for path in _llm_yaml_candidates():
        if path.is_file():
            cfg = LLMConfig.from_yaml(str(path))
            if cfg.api_key.strip() and cfg.model.strip():
                if cfg.backend not in ("openai", "vllm", "vllm-clone"):
                    cfg.backend = "openai"
                return cfg
    pytest.skip(
        "未配置 REACT_TEST_LLM_API_KEY / REACT_TEST_LLM_MODEL，"
        "且未找到可用的 config/llm_core/config.yaml"
    )


def api_llm_from_env() -> LLM:
    return LLM(_load_llm_config())


def api_llm_optional() -> LLM | None:
    for path in _llm_yaml_candidates():
        if path.is_file():
            cfg = LLMConfig.from_yaml(str(path))
            if cfg.api_key.strip() and cfg.model.strip():
                return LLM(cfg)
    api_key = os.environ.get("REACT_TEST_LLM_API_KEY", "").strip()
    model = os.environ.get("REACT_TEST_LLM_MODEL", "").strip()
    if not api_key or not model:
        return None
    return api_llm_from_env()
