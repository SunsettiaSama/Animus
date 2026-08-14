from __future__ import annotations

from worker.tools.builtin.commands.lookup import CommandLookupAction
from worker.tools.builtin.commands.runners import (
    BashRunAction,
    CmdRunAction,
    PowershellRunAction,
)

LATENT_SHELL_TOOLS: list[str] = ["powershell_run", "bash_run", "cmd_run"]
PROMPT_LOOKUP_TOOLS: list[str] = ["tool_search", "command_lookup"]

__all__ = [
    "BashRunAction",
    "CmdRunAction",
    "CommandLookupAction",
    "PowershellRunAction",
    "LATENT_SHELL_TOOLS",
    "PROMPT_LOOKUP_TOOLS",
]
