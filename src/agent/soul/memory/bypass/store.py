from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path

from .node import StackMemoryUnit


class StackMemoryStore:
    """增量式 JSONL 栈存储。

    - ``push``：向文件末尾追加一行即完成持久化，无全量重写、无索引重建；
    - ``items``：自栈顶（最新）向栈底（最旧）扫描；
    - 超过 ``max_entries`` 时从栈底淘汰，此时才整体重写一次文件。
    """

    def __init__(self, path: str | os.PathLike, *, max_entries: int = 2000) -> None:
        self._path = Path(path)
        self._max_entries = max(1, int(max_entries))
        self._stack: deque[StackMemoryUnit] = deque()  # 右端 = 栈顶（最新）
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        self._stack.clear()
        if not self._path.is_file():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    self._stack.append(StackMemoryUnit.from_dict(payload))
                except Exception:
                    continue
        self._trim()

    def _trim(self) -> None:
        if len(self._stack) <= self._max_entries:
            return
        while len(self._stack) > self._max_entries:
            self._stack.popleft()
        self._rewrite()

    def _rewrite(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for unit in self._stack:
                fh.write(json.dumps(unit.to_dict(), ensure_ascii=False))
                fh.write("\n")
        os.replace(tmp, self._path)

    def push(self, unit: StackMemoryUnit) -> StackMemoryUnit:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(unit.to_dict(), ensure_ascii=False))
            fh.write("\n")
        self._stack.append(unit)
        self._trim()
        return unit

    def items(self, *, limit: int | None = None) -> list[StackMemoryUnit]:
        """栈顶在前（最新优先）。"""
        if limit is None:
            return list(reversed(self._stack))
        limit = max(0, int(limit))
        if limit == 0:
            return []
        out: list[StackMemoryUnit] = []
        for unit in reversed(self._stack):
            out.append(unit)
            if len(out) >= limit:
                break
        return out

    def bottom_up(self) -> list[StackMemoryUnit]:
        return list(self._stack)

    def rewrite(self) -> None:
        """全量重写（仅在需要回写 recall_count 等原地变更时调用）。"""
        self._rewrite()

    def clear(self) -> int:
        n = len(self._stack)
        self._stack.clear()
        if self._path.exists():
            self._path.unlink()
        return n

    def __len__(self) -> int:
        return len(self._stack)
