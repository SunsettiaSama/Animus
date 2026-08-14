"""Command catalog lookup injects observations, never dumps full catalogs."""
from __future__ import annotations

from worker.tools.builtin.commands.catalog import all_entries, search_commands
from worker.tools.builtin.commands.lookup import CommandLookupAction
from worker.tools.manager import ToolManager, LATENT_SHELL_TOOLS


def test_catalog_groups_cover_three_families():
    entries = all_entries()
    families = {e.family for e in entries}
    assert families == {"powershell", "bash", "winnt"}
    assert any(e.group == "filesystem" for e in entries)


def test_search_returns_run_tool():
    hits = search_commands("list files", family="powershell", top_k=3)
    assert hits
    assert all(h.run_tool == "powershell_run" for h in hits)


def test_search_chinese_pwd_hits_get_location():
    hits = search_commands("显示当前目录", family="powershell", top_k=5)
    assert hits
    assert any(h.name == "Get-Location" for h in hits)


def test_command_lookup_observation_mentions_run_tool():
    action = CommandLookupAction()
    text = action.execute(query="进程", family="bash", top_k=3)
    assert "bash_run" in text
    assert "run_tool=" in text
    assert "未写入系统工具列表" in text


def test_prompt_descriptions_exclude_latent_runners_and_full_catalog():
    tm = ToolManager()
    desc = tm.primary_descriptions(tm.prompt_tool_names())
    for name in LATENT_SHELL_TOOLS:
        assert name not in desc
    blob = "\n".join(desc.values())
    assert "Get-ChildItem" not in blob
    assert "tasklist" not in blob
