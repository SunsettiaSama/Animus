from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from config.agent.persona_config import PersonaConfig
from config.soul.config import SoulConfig
from agent.soul.service import SoulService


class _MockLLM:
    """最小 LLM 桩：返回 JSON 字符串，避免 MagicMock 污染 regex/json 解析。"""

    _DEFAULT_JSON = '{"intention":"rest","context":""}'
    _CHAT_REPLY = "你好，我在这里。"

    def invoke(self, *args, **kwargs):
        return MagicMock(content=self._DEFAULT_JSON)

    def stream(self, *args, **kwargs):
        yield MagicMock(content="{}")

    def generate_messages(self, messages, **kwargs) -> str:
        if any("你好" in str(getattr(m, "content", "")) for m in messages):
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
def persona_cfg(soul_temp_dir):
    return PersonaConfig(
        enabled=True,
        persona_dir=os.path.join(soul_temp_dir, "persona"),
        evolution_enabled=False,
    )


@pytest.fixture
def soul_service(soul_temp_dir, persona_cfg, mock_llm):
    return SoulService(
        life_dir=os.path.join(soul_temp_dir, "life"),
        persona_cfg=persona_cfg,
        mysql_client=MagicMock(),
        primary_llm=mock_llm,
        cfg=SoulConfig(),
    )
