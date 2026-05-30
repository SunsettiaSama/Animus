from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from config.agent.persona_config import PersonaConfig
from config.soul.config import SoulConfig
from config.soul.memory.infra_config import SoulMemoryInfraConfig
from agent.soul.service import SoulService
from infra.memory import MemoryInfraService


class _MockLLM:
    """Minimal LLM stub: returns JSON strings, avoids MagicMock polluting parsers."""

    _DEFAULT_JSON = '{"intention":"rest","context":""}'
    _CHAT_REPLY = "hello"

    def invoke(self, *args, **kwargs):
        return MagicMock(content=self._DEFAULT_JSON)

    def stream(self, *args, **kwargs):
        yield MagicMock(content="{}")

    def generate_messages(self, messages, **kwargs) -> str:
        if any("\u4f60\u597d" in str(getattr(m, "content", "")) for m in messages):
            return self._CHAT_REPLY
        return self._DEFAULT_JSON

    def stream_generate_messages(self, messages, **kwargs):
        text = self.generate_messages(messages, **kwargs)
        for ch in text:
            yield ch


@pytest.fixture
def soul_temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def mock_llm():
    return _MockLLM()


@pytest.fixture
def disabled_memory_infra():
    return MemoryInfraService(
        cfg=SoulMemoryInfraConfig(enabled=False),
        embedding=None,
        vectors=None,
    )


@pytest.fixture
def persona_cfg(soul_temp_dir):
    return PersonaConfig(
        enabled=True,
        persona_dir=os.path.join(soul_temp_dir, "persona"),
        evolution_enabled=False,
    )


@pytest.fixture
def soul_service(soul_temp_dir, persona_cfg, mock_llm, disabled_memory_infra):
    return SoulService(
        life_dir=os.path.join(soul_temp_dir, "life"),
        persona_cfg=persona_cfg,
        mysql_client=MagicMock(),
        primary_llm=mock_llm,
        cfg=SoulConfig(),
        memory_infra=disabled_memory_infra,
    )
