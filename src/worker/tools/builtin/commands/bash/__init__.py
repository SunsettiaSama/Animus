from __future__ import annotations

from worker.tools.builtin.commands.schema import CommandEntry, CommandGroup

_RUN = "bash_run"
_FAMILY = "bash"


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
            "pwd",
            "显示当前工作目录",
            "pwd",
            "pwd",
            "pwd",
            "cwd",
            "directory",
        ),
        _entry(
            "filesystem",
            "ls",
            "列出目录中的文件与子目录（list files）",
            "ls",
            "ls -la",
            "list",
            "files",
            "dir",
        ),
        _entry(
            "filesystem",
            "cd",
            "切换当前工作目录",
            "cd <path>",
            "cd .",
            "chdir",
            "directory",
        ),
        _entry(
            "filesystem",
            "find",
            "按条件查找文件",
            "find <path> -name <pattern>",
            "find . -maxdepth 2 -type f",
            "find",
            "search",
            "files",
        ),
    ),
)

PROCESS = CommandGroup(
    family=_FAMILY,
    group="process",
    entries=(
        _entry(
            "process",
            "ps",
            "列出当前进程",
            "ps",
            "ps aux",
            "process",
            "进程",
            "tasks",
        ),
        _entry(
            "process",
            "top",
            "实时查看进程资源占用",
            "top",
            "top -b -n 1 | head",
            "process",
            "monitor",
            "cpu",
        ),
        _entry(
            "process",
            "kill",
            "向进程发送信号",
            "kill <pid>",
            "kill -15 1234",
            "process",
            "stop",
            "signal",
        ),
    ),
)

ENV = CommandGroup(
    family=_FAMILY,
    group="env",
    entries=(
        _entry(
            "env",
            "env",
            "打印环境变量",
            "env",
            "env | head",
            "environment",
            "variables",
        ),
        _entry(
            "env",
            "export",
            "设置环境变量（当前 shell）",
            "export NAME=value",
            "export MY_VAR=hello",
            "set",
            "environment",
        ),
        _entry(
            "env",
            "echo",
            "输出文本或变量值",
            "echo <text>",
            "echo $PATH",
            "print",
            "variable",
        ),
    ),
)

NETWORK = CommandGroup(
    family=_FAMILY,
    group="network",
    entries=(
        _entry(
            "network",
            "curl",
            "发起 HTTP 请求或下载",
            "curl <url>",
            "curl -I https://example.com",
            "http",
            "web",
            "download",
        ),
        _entry(
            "network",
            "ping",
            "测试网络连通性",
            "ping -c 4 <host>",
            "ping -c 4 example.com",
            "network",
            "connectivity",
        ),
        _entry(
            "network",
            "wget",
            "下载网络资源",
            "wget <url>",
            "wget -qO- https://example.com",
            "download",
            "http",
            "web",
        ),
    ),
)

TEXT = CommandGroup(
    family=_FAMILY,
    group="text",
    entries=(
        _entry(
            "text",
            "grep",
            "在文本中搜索匹配行",
            "grep <pattern> <file>",
            "grep -n error app.log",
            "search",
            "text",
            "regex",
        ),
        _entry(
            "text",
            "sed",
            "流式编辑文本",
            "sed 's/old/new/' <file>",
            "sed -n '1,5p' file.txt",
            "edit",
            "text",
            "replace",
        ),
        _entry(
            "text",
            "cat",
            "输出文件内容",
            "cat <file>",
            "cat README.md",
            "read",
            "file",
            "text",
        ),
    ),
)

GROUPS: tuple[CommandGroup, ...] = (
    FILESYSTEM,
    PROCESS,
    ENV,
    NETWORK,
    TEXT,
)
