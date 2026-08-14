"""Registry online audit — expected tools registered; plan_tools excluded."""
from __future__ import annotations

from worker.tools.manager import EXCLUDED_FROM_ONLINE, ToolManager
from worker.tools.builtin.impl import plan_tools


def test_expected_impl_tools_are_online():
    tm = ToolManager()
    names = set(tm.registry.names())
    required = {
        "calculator",
        "get_datetime",
        "web_search",
        "web_fetch",
        "file_read",
        "file_write",
        "python_run",
        "command_lookup",
        "powershell_run",
        "bash_run",
        "cmd_run",
        "note_write",
        "knowledge_hybrid_search",
        "scheduler_add",
    }
    missing = required - names
    assert not missing, f"missing online tools: {missing}"


def test_plan_tools_are_excluded_from_online_registry():
    tm = ToolManager()
    names = set(tm.registry.names())
    for excluded in EXCLUDED_FROM_ONLINE:
        assert excluded not in names
    # Module still exists but is not the live injection path.
    assert hasattr(plan_tools, "PlanStatusAction")
