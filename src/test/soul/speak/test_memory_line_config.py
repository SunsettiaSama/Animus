"""Speak 记忆行长度配置：speak_memory_line_max_content。"""
from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.memory.domain.labels import memory_kind_prompt_label
from agent.soul.memory.graph.scored import ScoredUnit
from config.soul.memory.service_config import MemoryServiceConfig


def test_render_line_respects_speak_memory_line_max_content():
    cfg = MemoryServiceConfig(speak_memory_line_max_content=320)
    unit = MagicMock()
    unit.MEMORY_TYPE = "factual"
    unit.focus = "标题"
    long_body = "叙" * 400
    unit.fact = long_body
    unit.reconstructed_fact = ""
    unit.narrative = ""
    unit.content = ""
    unit.agent_relation = ""
    unit.trait_changelog = ""
    unit.label = ""

    line = ScoredUnit(unit).render_line(max_content=cfg.speak_memory_line_max_content)
    assert line.startswith(f"[{memory_kind_prompt_label('factual')}] 标题：")
    body = line.split("：", 1)[1]
    assert len(body) == 320
    assert body == long_body[:320]
