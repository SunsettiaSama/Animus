"""coding/tools.py — CodingToolSuite：为代码生成节点提供可调用工具集。

工具协议
--------
每个工具是一个可调用对象，接受关键字参数，返回字符串观察结果。
工具集通过 CodingToolSuite 统一注册和调度。

内置工具
--------
read_file    — 读取工作区文件内容
write_file   — 将内容写入（或覆盖）文件
append_file  — 追加内容到文件末尾
list_dir     — 列出目录下的文件与子目录
run_python   — 在子进程中运行 Python 代码片段，返回 stdout / stderr
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ── 工具协议类型 ──────────────────────────────────────────────────────────────

ToolCallable = Callable[..., str]  # (**kwargs) -> observation_str


@dataclass(frozen=True)
class ToolSpec:
    """工具声明，注入 LLM prompt 时使用。"""

    name: str
    description: str
    parameters: str  # 参数说明，plain text（无需 JSON schema）


# ── 内置工具实现 ──────────────────────────────────────────────────────────────

def _read_file(path: str, max_chars: int = 8000) -> str:
    p = Path(path)
    if not p.exists():
        return f"[read_file] 文件不存在：{path}"
    content = p.read_text(encoding="utf-8", errors="replace")
    if len(content) > max_chars:
        return content[:max_chars] + f"\n[内容已截断，共 {len(content)} 字符]"
    return content


def _write_file(path: str, content: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"[write_file] 已写入 {p}（{len(content)} 字符）"


def _append_file(path: str, content: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(content)
    return f"[append_file] 已追加 {len(content)} 字符到 {p}"


def _list_dir(path: str = ".", max_entries: int = 60) -> str:
    p = Path(path)
    if not p.exists():
        return f"[list_dir] 路径不存在：{path}"
    entries: list[str] = []
    for item in sorted(p.iterdir()):
        tag = "DIR" if item.is_dir() else "FILE"
        entries.append(f"  {tag}  {item.name}")
        if len(entries) >= max_entries:
            entries.append(f"  ... (超过 {max_entries} 项，已截断)")
            break
    return f"[list_dir] {p}\n" + "\n".join(entries)


def _run_python(code: str, timeout: int = 15, workdir: str = ".") -> str:
    dedented = textwrap.dedent(code)
    result = subprocess.run(
        [sys.executable, "-c", dedented],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=workdir,
    )
    parts: list[str] = []
    if result.stdout.strip():
        parts.append(f"STDOUT:\n{result.stdout.strip()}")
    if result.stderr.strip():
        parts.append(f"STDERR:\n{result.stderr.strip()}")
    parts.append(f"exit_code={result.returncode}")
    return "\n".join(parts) if parts else "(无输出)"


# ── CodingToolSuite ───────────────────────────────────────────────────────────

_BUILTIN_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="read_file",
        description="读取指定路径的文件内容。",
        parameters="path: str — 文件路径；max_chars: int = 8000 — 最大返回字符数",
    ),
    ToolSpec(
        name="write_file",
        description="将 content 写入指定路径（覆盖已有内容；自动创建父目录）。",
        parameters="path: str — 目标路径；content: str — 写入内容",
    ),
    ToolSpec(
        name="append_file",
        description="将 content 追加到指定文件末尾。",
        parameters="path: str — 目标路径；content: str — 追加内容",
    ),
    ToolSpec(
        name="list_dir",
        description="列出目录下的文件与子目录。",
        parameters="path: str = '.' — 目录路径；max_entries: int = 60",
    ),
    ToolSpec(
        name="run_python",
        description="在子进程中执行 Python 代码片段，返回 stdout/stderr 与退出码。",
        parameters="code: str — Python 代码；timeout: int = 15 — 超时秒数；workdir: str = '.'",
    ),
]

_BUILTIN_IMPLS: dict[str, ToolCallable] = {
    "read_file":   _read_file,
    "write_file":  _write_file,
    "append_file": _append_file,
    "list_dir":    _list_dir,
    "run_python":  _run_python,
}


@dataclass
class CodingToolSuite:
    """代码生成节点的工具套组。

    默认激活所有内置工具（read / write / append / list_dir / run_python）。
    可通过 register() 追加自定义工具，或通过 disable() 禁用内置工具。

    使用示例
    --------
    ::

        suite = CodingToolSuite()
        suite.disable("append_file")                     # 不需要追加写
        suite.register("search_pypi", my_search, spec)  # 自定义工具

        cfg = CodingConfig()
        executor = CodeNodeExecutor(llm_call, cfg.language, tools=suite)
    """

    _impls: dict[str, ToolCallable] = field(
        default_factory=lambda: dict(_BUILTIN_IMPLS), init=False
    )
    _specs: dict[str, ToolSpec] = field(
        default_factory=lambda: {s.name: s for s in _BUILTIN_SPECS}, init=False
    )

    def register(
        self,
        name: str,
        impl: ToolCallable,
        spec: ToolSpec | None = None,
    ) -> None:
        self._impls[name] = impl
        self._specs[name] = spec or ToolSpec(
            name=name,
            description=f"自定义工具 {name}。",
            parameters="（无参数说明）",
        )

    def disable(self, *names: str) -> None:
        for n in names:
            self._impls.pop(n, None)
            self._specs.pop(n, None)

    def call(self, tool_name: str, **kwargs: Any) -> str:
        if tool_name not in self._impls:
            return f"[tool_error] 未知工具：{tool_name}。可用工具：{list(self._impls)}"
        return self._impls[tool_name](**kwargs)

    def available_names(self) -> list[str]:
        return list(self._impls)

    def render_tool_list(self) -> str:
        lines: list[str] = []
        for spec in self._specs.values():
            lines.append(f"- {spec.name}: {spec.description}")
            lines.append(f"  参数: {spec.parameters}")
        return "\n".join(lines)
