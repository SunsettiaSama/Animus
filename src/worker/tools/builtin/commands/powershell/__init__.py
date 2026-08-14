from __future__ import annotations

from worker.tools.builtin.commands.schema import CommandEntry, CommandGroup

_RUN = "powershell_run"
_FAMILY = "powershell"


def _entry(
    group: str,
    name: str,
    synopsis: str,
    template: str,
    example: str,
    *tags: str,
) -> CommandEntry:
    entry_id = f"{_FAMILY}.{group}.{name}"
    return CommandEntry(
        id=entry_id,
        family=_FAMILY,
        group=group,
        name=name,
        synopsis=synopsis,
        template=template,
        example=example,
        run_tool=_RUN,
        tags=tags,
    )


FILESYSTEM = CommandGroup(
    family=_FAMILY,
    group="filesystem",
    entries=(
        _entry(
            "filesystem",
            "Get-Location",
            "显示当前工作目录（pwd/cwd）",
            "Get-Location",
            "Get-Location",
            "pwd",
            "cwd",
            "location",
            "directory",
        ),
        _entry(
            "filesystem",
            "Get-ChildItem",
            "列出目录中的文件与子目录（list files）",
            "Get-ChildItem",
            "Get-ChildItem -Name",
            "list",
            "files",
            "ls",
            "dir",
        ),
        _entry(
            "filesystem",
            "Set-Location",
            "切换当前工作目录",
            "Set-Location <path>",
            "Set-Location .",
            "cd",
            "chdir",
            "directory",
        ),
        _entry(
            "filesystem",
            "Test-Path",
            "检查路径是否存在",
            "Test-Path <path>",
            "Test-Path .",
            "exists",
            "path",
            "file",
        ),
    ),
)

PROCESS = CommandGroup(
    family=_FAMILY,
    group="process",
    entries=(
        _entry(
            "process",
            "Get-Process",
            "列出或查看进程",
            "Get-Process",
            "Get-Process | Select-Object -First 5 Name,Id",
            "process",
            "ps",
            "task",
        ),
        _entry(
            "process",
            "Start-Process",
            "启动新进程",
            "Start-Process <path>",
            "Start-Process notepad.exe",
            "start",
            "launch",
            "process",
        ),
        _entry(
            "process",
            "Stop-Process",
            "停止指定进程",
            "Stop-Process -Id <pid>",
            "Stop-Process -Name notepad",
            "kill",
            "stop",
            "process",
        ),
    ),
)

ENV = CommandGroup(
    family=_FAMILY,
    group="env",
    entries=(
        _entry(
            "env",
            "Get-ChildItem Env:",
            "列出环境变量",
            "Get-ChildItem Env:",
            "Get-ChildItem Env: | Select-Object -First 10 Name,Value",
            "env",
            "environment",
            "variables",
        ),
        _entry(
            "env",
            "Set-Item Env:",
            "设置环境变量（当前会话）",
            "Set-Item -Path Env:<NAME> -Value <value>",
            "Set-Item -Path Env:MY_VAR -Value hello",
            "export",
            "set",
            "environment",
        ),
        _entry(
            "env",
            "$env:NAME",
            "读取单个环境变量",
            "$env:<NAME>",
            "$env:PATH",
            "env",
            "variable",
            "read",
        ),
    ),
)

NETWORK = CommandGroup(
    family=_FAMILY,
    group="network",
    entries=(
        _entry(
            "network",
            "Test-NetConnection",
            "测试网络连通性",
            "Test-NetConnection <host>",
            "Test-NetConnection example.com -Port 443",
            "ping",
            "network",
            "connectivity",
        ),
        _entry(
            "network",
            "Invoke-WebRequest",
            "发起 HTTP 请求",
            "Invoke-WebRequest -Uri <url>",
            "Invoke-WebRequest -Uri https://example.com -UseBasicParsing",
            "http",
            "web",
            "curl",
        ),
        _entry(
            "network",
            "Resolve-DnsName",
            "解析 DNS 记录",
            "Resolve-DnsName <name>",
            "Resolve-DnsName example.com",
            "dns",
            "lookup",
            "network",
        ),
    ),
)

SERVICE = CommandGroup(
    family=_FAMILY,
    group="service",
    entries=(
        _entry(
            "service",
            "Get-Service",
            "列出 Windows 服务",
            "Get-Service",
            "Get-Service | Select-Object -First 10 Name,Status",
            "service",
            "windows",
            "status",
        ),
        _entry(
            "service",
            "Start-Service",
            "启动服务",
            "Start-Service <name>",
            "Start-Service w32time",
            "service",
            "start",
        ),
        _entry(
            "service",
            "Stop-Service",
            "停止服务",
            "Stop-Service <name>",
            "Stop-Service w32time",
            "service",
            "stop",
        ),
    ),
)

GROUPS: tuple[CommandGroup, ...] = (
    FILESYSTEM,
    PROCESS,
    ENV,
    NETWORK,
    SERVICE,
)
