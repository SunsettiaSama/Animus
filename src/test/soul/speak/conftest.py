"""Speak 子目录 pytest 配置（与 src/test/conftest.py 选项保持一致）。"""
from __future__ import annotations

import os

import pytest


def _option_registered(parser: pytest.Parser, dest: str) -> bool:
    return any(getattr(opt, "dest", None) == dest for opt in parser._anonymous.options)


def pytest_addoption(parser: pytest.Parser) -> None:
    if not _option_registered(parser, "run_speak_live"):
        parser.addoption(
            "--run-speak-live",
            action="store_true",
            default=False,
            help="使用真实 LLM 跑 speak 冒烟（需 --speak-base-url / --speak-api-key）",
        )
    if not _option_registered(parser, "speak_model"):
        parser.addoption(
            "--speak-model",
            default=os.environ.get("SPEAK_SMOKE_MODEL", "deepseek-chat"),
            help="speak live 冒烟使用的模型名",
        )
    if not _option_registered(parser, "speak_base_url"):
        parser.addoption(
            "--speak-base-url",
            default=os.environ.get("SPEAK_SMOKE_BASE_URL"),
            help="speak live 冒烟 API base URL",
        )
    if not _option_registered(parser, "speak_api_key"):
        parser.addoption(
            "--speak-api-key",
            default=os.environ.get("SPEAK_SMOKE_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            help="speak live 冒烟 API key",
        )
