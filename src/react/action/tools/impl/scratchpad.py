from __future__ import annotations

import threading
from typing import ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class ScratchpadStore:
    """
    会话级内存草稿本（K-V 存储）。

    由 TaoLoop 持有，生命周期与会话一致。通过 reset() 在新会话开始时清空。
    线程安全：所有操作由内部锁保护。
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._lock = threading.Lock()

    def write(self, key: str, content: str) -> None:
        with self._lock:
            self._store[key] = content

    def read(self, key: str) -> str | None:
        with self._lock:
            return self._store.get(key)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def all_keys(self) -> list[str]:
        with self._lock:
            return sorted(self._store.keys())

    def all_items(self) -> dict[str, str]:
        with self._lock:
            return dict(self._store)

    def reset(self) -> None:
        with self._lock:
            self._store.clear()


class NoteWriteArgs(BaseModel):
    key: str = Field(..., min_length=1, description="笔记键名，如 'step1_result' 或 'plan'")
    content: str = Field(..., description="笔记内容")


class NoteWriteAction(BaseAction):
    name: str = "note_write"
    description: str = (
        "向会话草稿本写入一条笔记（K-V 存储）。适合跨推理步骤保存中间结果。"
        "参数：key（键名），content（内容）"
    )
    args_model: ClassVar[type[BaseModel]] = NoteWriteArgs

    store: ScratchpadStore | None = None

    def execute(self, key: str, content: str, **kwargs) -> str:
        if self.store is None:
            raise RuntimeError("NoteWriteAction 需要 ScratchpadStore 注入。")
        self.store.write(key, content)
        return f"已写入草稿本：key={key!r}，共 {len(content)} 字符"


class NoteReadArgs(BaseModel):
    key: str = Field("", description="要读取的键名；留空则列出所有笔记摘要")


class NoteReadAction(BaseAction):
    name: str = "note_read"
    description: str = (
        "读取会话草稿本中的笔记。key 留空则列出所有条目的键名和内容摘要。"
        "参数：key（键名，留空则列出全部）"
    )
    args_model: ClassVar[type[BaseModel]] = NoteReadArgs

    store: ScratchpadStore | None = None

    def execute(self, key: str = "", **kwargs) -> str:
        if self.store is None:
            raise RuntimeError("NoteReadAction 需要 ScratchpadStore 注入。")
        if key:
            content = self.store.read(key)
            if content is None:
                return f"草稿本中不存在键：{key!r}"
            return f"[{key}]\n\n{content}"
        items = self.store.all_items()
        if not items:
            return "草稿本为空。"
        lines = [f"草稿本共 {len(items)} 条："]
        for k, v in sorted(items.items()):
            preview = v[:100].replace("\n", " ")
            suffix = "..." if len(v) > 100 else ""
            lines.append(f"  {k!r}: {preview}{suffix}")
        return "\n".join(lines)


class NoteDeleteArgs(BaseModel):
    key: str = Field(..., min_length=1, description="要删除的键名")


class NoteDeleteAction(BaseAction):
    name: str = "note_delete"
    description: str = (
        "删除会话草稿本中的一条笔记。"
        "参数：key（键名）"
    )
    args_model: ClassVar[type[BaseModel]] = NoteDeleteArgs

    store: ScratchpadStore | None = None

    def execute(self, key: str, **kwargs) -> str:
        if self.store is None:
            raise RuntimeError("NoteDeleteAction 需要 ScratchpadStore 注入。")
        deleted = self.store.delete(key)
        if deleted:
            return f"已从草稿本删除：{key!r}"
        return f"草稿本中不存在键：{key!r}"
