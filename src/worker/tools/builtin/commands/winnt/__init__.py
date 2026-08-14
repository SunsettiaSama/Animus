from __future__ import annotations

from worker.tools.builtin.commands.schema import CommandEntry, CommandGroup

_RUN = "cmd_run"
_FAMILY = "winnt"


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
            "cd",
            "切换当前工作目录",
            "cd /d <path>",
            "cd /d .",
            "chdir",
            "directory",
        ),
        _entry(
            "filesystem",
            "dir",
            "列出目录中的文件与子目录（list files）",
            "dir",
            "dir /b",
            "list",
            "files",
            "ls",
        ),
        _entry(
            "filesystem",
            "copy",
            "复制文件",
            "copy <src> <dst>",
            "copy file.txt file.bak",
            "file",
            "copy",
        ),
        _entry(
            "filesystem",
            "type",
            "显示文件内容",
            "type <file>",
            "type README.txt",
            "read",
            "file",
            "cat",
        ),
    ),
)

PROCESS = CommandGroup(
    family=_FAMILY,
    group="process",
    entries=(
        _entry(
            "process",
            "tasklist",
            "列出当前进程",
            "tasklist",
            "tasklist /FI \"IMAGENAME eq notepad.exe\"",
            "process",
            "tasks",
            "进程",
        ),
        _entry(
            "process",
            "start",
            "启动程序或命令",
            "start \"\" <command>",
            "start \"\" notepad.exe",
            "launch",
            "process",
        ),
        _entry(
            "process",
            "taskkill",
            "终止进程",
            "taskkill /PID <pid> /F",
            "taskkill /IM notepad.exe /F",
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
            "set",
            "显示或设置环境变量",
            "set",
            "set PATH",
            "environment",
            "variables",
        ),
        _entry(
            "env",
            "set NAME=value",
            "设置环境变量（当前 cmd 会话）",
            "set NAME=value",
            "set MY_VAR=hello",
            "export",
            "environment",
        ),
    ),
)

NETWORK = CommandGroup(
    family=_FAMILY,
    group="network",
    entries=(
        _entry(
            "network",
            "ping",
            "测试网络连通性",
            "ping <host>",
            "ping example.com",
            "network",
            "connectivity",
        ),
        _entry(
            "network",
            "curl",
            "发起 HTTP 请求（Windows 10+）",
            "curl <url>",
            "curl -I https://example.com",
            "http",
            "web",
        ),
        _entry(
            "network",
            "nslookup",
            "查询 DNS 记录",
            "nslookup <name>",
            "nslookup example.com",
            "dns",
            "lookup",
        ),
    ),
)

SYSTEM = CommandGroup(
    family=_FAMILY,
    group="system",
    entries=(
        _entry(
            "system",
            "systeminfo",
            "显示系统配置摘要",
            "systeminfo",
            "systeminfo | findstr /B \"OS Name\"",
            "system",
            "info",
            "windows",
        ),
        _entry(
            "system",
            "hostname",
            "显示计算机名",
            "hostname",
            "hostname",
            "system",
            "name",
        ),
        _entry(
            "system",
            "ver",
            "显示 Windows 版本",
            "ver",
            "ver",
            "version",
            "system",
        ),
    ),
)

GROUPS: tuple[CommandGroup, ...] = (
    FILESYSTEM,
    PROCESS,
    ENV,
    NETWORK,
    SYSTEM,
)
