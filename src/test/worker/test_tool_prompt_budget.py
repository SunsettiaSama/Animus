"""Prompt stays lean; package tools stay callable."""
from __future__ import annotations

from worker.tools.manager import (
    DEFAULT_PRIMARY,
    LATENT_SHELL_TOOLS,
    PROMPT_LOOKUP_TOOLS,
    ToolManager,
)


def test_prompt_tool_list_is_primary_plus_lookups_only():
    tm = ToolManager()
    names = tm.prompt_tool_names()
    assert set(DEFAULT_PRIMARY).issubset(set(names))
    assert set(PROMPT_LOOKUP_TOOLS).issubset(set(names))
    for latent in LATENT_SHELL_TOOLS:
        assert latent not in names

    desc = tm.primary_descriptions(names)
    assert "calculator" in desc
    assert "tool_search" in desc
    assert "command_lookup" in desc
    for latent in LATENT_SHELL_TOOLS:
        assert latent not in desc
    assert "file_read" not in desc
    assert "python_run" not in desc


def test_allowed_actions_include_package_and_latent_shell():
    tm = ToolManager()
    allowed = tm.resolve_allowed_actions("executor")
    assert "calculator" in allowed
    assert "tool_search" in allowed
    assert "command_lookup" in allowed
    assert "file_read" in allowed
    for latent in LATENT_SHELL_TOOLS:
        assert latent in allowed


def test_category_summary_has_no_tool_name_dump():
    tm = ToolManager()
    summary = tm.category_summary()
    assert "command_lookup" not in summary or "类别" in summary
    assert "web_search," not in summary
    assert "file_read," not in summary
    assert "tool_search(query)" in summary
    assert "command_lookup(query)" in summary
    assert "仅展示类别" in summary
