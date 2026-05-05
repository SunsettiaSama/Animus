from __future__ import annotations

import os
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class FileReadArgs(BaseModel):
    path: str = Field(..., min_length=1, description="文件路径（相对于沙箱工作区，或绝对路径若允许）")
    encoding: str = Field("utf-8", description="文件编码，默认 utf-8")
    max_chars: int = Field(20000, ge=1, le=200000, description="最大读取字符数，默认 20000")


class FileReadAction(BaseAction):
    name: str = "file_read"
    description: str = (
        "读取本地文件内容，支持 txt / json / csv / md 等纯文本格式。"
        "参数：path（文件路径），encoding（编码，默认 utf-8），max_chars（最大字符数，默认 20000）"
    )
    args_model: ClassVar[type[BaseModel]] = FileReadArgs

    sandbox: Any = None

    def execute(self, path: str, encoding: str = "utf-8", max_chars: int = 20000, **kwargs) -> str:
        resolved = self.sandbox.resolve_path(path) if self.sandbox else path
        file_size = os.path.getsize(resolved)
        max_size = self.sandbox.cfg.max_file_size_bytes if self.sandbox else 10_485_760
        if file_size > max_size:
            raise ValueError(
                f"文件过大：{file_size} 字节，超过沙箱限制 {max_size} 字节"
            )
        with open(resolved, encoding=encoding) as f:
            content = f.read(max_chars)
        truncated = os.path.getsize(resolved) > max_chars
        suffix = f"\n\n[内容已截断，文件共 {file_size} 字节，仅读取前 {max_chars} 字符]" if truncated else ""
        return f"[{path}]\n\n{content}{suffix}"


class FileWriteArgs(BaseModel):
    path: str = Field(..., min_length=1, description="目标文件路径（相对于沙箱工作区）")
    content: str = Field(..., description="要写入的内容")
    mode: Literal["write", "append"] = Field("write", description="'write'（覆盖）或 'append'（追加），默认 write")
    encoding: str = Field("utf-8", description="文件编码，默认 utf-8")


class FileWriteAction(BaseAction):
    name: str = "file_write"
    description: str = (
        "向沙箱工作区写入或追加文件内容。"
        "参数：path（文件路径），content（内容），mode（write/append，默认 write），encoding（默认 utf-8）"
    )
    args_model: ClassVar[type[BaseModel]] = FileWriteArgs

    sandbox: Any = None

    def execute(self, path: str, content: str, mode: str = "write", encoding: str = "utf-8", **kwargs) -> str:
        resolved = self.sandbox.resolve_path(path) if self.sandbox else path
        resolved.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "a" if mode == "append" else "w"
        with open(resolved, open_mode, encoding=encoding) as f:
            f.write(content)
        action_label = "追加" if mode == "append" else "写入"
        return f"已{action_label} {len(content)} 字符到 {path}"


class FileListArgs(BaseModel):
    path: str = Field(".", description="目录路径（相对于沙箱工作区），默认为工作区根目录")
    recursive: bool = Field(False, description="是否递归列出子目录，默认 False")


class FileListAction(BaseAction):
    name: str = "file_list"
    description: str = (
        "列出沙箱工作区目录下的文件和子目录。"
        "参数：path（目录路径，默认为工作区根），recursive（是否递归，默认 false）"
    )
    args_model: ClassVar[type[BaseModel]] = FileListArgs

    sandbox: Any = None

    def execute(self, path: str = ".", recursive: bool = False, **kwargs) -> str:
        resolved = self.sandbox.resolve_path(path) if self.sandbox else path
        if not os.path.isdir(resolved):
            return f"路径不是目录或不存在：{path}"
        entries: list[str] = []
        if recursive:
            for root, dirs, files in os.walk(resolved):
                rel_root = os.path.relpath(root, resolved)
                prefix = "" if rel_root == "." else rel_root + os.sep
                for d in sorted(dirs):
                    entries.append(f"[目录] {prefix}{d}/")
                for fn in sorted(files):
                    size = os.path.getsize(os.path.join(root, fn))
                    entries.append(f"       {prefix}{fn}  ({size} 字节)")
        else:
            for entry in sorted(os.listdir(resolved)):
                full = os.path.join(resolved, entry)
                if os.path.isdir(full):
                    entries.append(f"[目录] {entry}/")
                else:
                    size = os.path.getsize(full)
                    entries.append(f"       {entry}  ({size} 字节)")
        if not entries:
            return f"目录为空：{path}"
        return f"目录列表：{path}\n" + "\n".join(entries)


class FileExistsArgs(BaseModel):
    path: str = Field(..., min_length=1, description="要检查的路径（相对于沙箱工作区）")


class FileExistsAction(BaseAction):
    name: str = "file_exists"
    description: str = (
        "检查沙箱工作区中的文件或目录是否存在。"
        "参数：path（路径）"
    )
    args_model: ClassVar[type[BaseModel]] = FileExistsArgs

    sandbox: Any = None

    def execute(self, path: str, **kwargs) -> str:
        resolved = self.sandbox.resolve_path(path) if self.sandbox else path
        exists = os.path.exists(resolved)
        if exists:
            kind = "目录" if os.path.isdir(resolved) else "文件"
            size_info = ""
            if os.path.isfile(resolved):
                size_info = f"，大小 {os.path.getsize(resolved)} 字节"
            return f"存在（{kind}）：{path}{size_info}"
        return f"不存在：{path}"
