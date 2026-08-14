from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from worker.tools.base import BaseAction


class ShellRunArgs(BaseModel):
    command: str = Field(..., min_length=1, description="要在沙箱工作目录内执行的 shell 命令字符串")


class PowershellRunAction(BaseAction):
    name: str = "powershell_run"
    description: str = (
        "在 sandbox 工作目录内通过 PowerShell 执行命令（HIGH risk，不进 prompt）。"
        "参数：command（PowerShell 命令字符串）"
    )
    args_model: ClassVar[type[BaseModel]] = ShellRunArgs
    sandbox: Any = None

    def execute(self, command: str, **kwargs) -> str:
        if self.sandbox is None:
            raise RuntimeError("powershell_run 需要 SandboxManager 注入，沙箱未初始化。")
        return self.sandbox.exec_shell("powershell", command)


class BashRunAction(BaseAction):
    name: str = "bash_run"
    description: str = (
        "在 sandbox 工作目录内通过 bash 执行命令（HIGH risk，不进 prompt）。"
        "参数：command（bash 命令字符串）"
    )
    args_model: ClassVar[type[BaseModel]] = ShellRunArgs
    sandbox: Any = None

    def execute(self, command: str, **kwargs) -> str:
        if self.sandbox is None:
            raise RuntimeError("bash_run 需要 SandboxManager 注入，沙箱未初始化。")
        return self.sandbox.exec_shell("bash", command)


class CmdRunAction(BaseAction):
    name: str = "cmd_run"
    description: str = (
        "在 sandbox 工作目录内通过 cmd.exe 执行命令（HIGH risk，不进 prompt）。"
        "参数：command（cmd 命令字符串）"
    )
    args_model: ClassVar[type[BaseModel]] = ShellRunArgs
    sandbox: Any = None

    def execute(self, command: str, **kwargs) -> str:
        if self.sandbox is None:
            raise RuntimeError("cmd_run 需要 SandboxManager 注入，沙箱未初始化。")
        return self.sandbox.exec_shell("cmd", command)
