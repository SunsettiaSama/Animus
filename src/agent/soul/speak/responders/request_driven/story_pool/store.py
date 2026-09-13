"""剧情池持久化：池条目 + 活体剧情快照的 JSON 读写。

只做序列化与原子落盘，理解数据形状、不理解业务：
- ``<dir>/<key>.json`` 结构：{"version": 1, "entries": [...], "live": {...}|null}
- 条目/快照内容是 state.core 对象的 snapshot() 纯 dict（PlotArc/PlotFlow/
  PresenceCard/NarrativeCard 均自带 snapshot/from_dict 往返）。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any

_POOL_VERSION = 1
_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_.\-]+")


def sanitize_key(raw: str) -> str:
    """session/channel key → 文件名安全串。"""
    key = _SAFE_KEY_RE.sub("_", str(raw or "").strip()).strip("._")
    return key[:80] or "default"


@dataclass
class PoolFile:
    """一个 pool key 下的全部落盘内容。"""

    entries: list[dict[str, Any]] = field(default_factory=list)
    live: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"version": _POOL_VERSION, "entries": self.entries, "live": self.live}


class StoryPoolStore:
    """JSON 文件读写；线程安全（进程内锁 + 临时文件原子替换）。"""

    def __init__(self, root_dir: str) -> None:
        self._root = str(root_dir or os.path.join(".react", "story_pool"))
        self._lock = threading.Lock()

    @property
    def root(self) -> str:
        return self._root

    def _path(self, key: str) -> str:
        return os.path.join(self._root, f"{sanitize_key(key)}.json")

    def load(self, key: str) -> PoolFile:
        path = self._path(key)
        with self._lock:
            if not os.path.exists(path):
                return PoolFile()
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                return PoolFile()
        if not isinstance(data, dict):
            return PoolFile()
        entries = data.get("entries") if isinstance(data.get("entries"), list) else []
        live = data.get("live") if isinstance(data.get("live"), dict) else None
        return PoolFile(entries=[e for e in entries if isinstance(e, dict)], live=live)

    def save(self, key: str, file: PoolFile) -> None:
        path = self._path(key)
        payload = json.dumps(file.to_dict(), ensure_ascii=False, indent=1)
        with self._lock:
            try:
                os.makedirs(self._root, exist_ok=True)
                fd, tmp = tempfile.mkstemp(
                    prefix=".tmp-story-", dir=self._root, suffix=".json"
                )
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                os.replace(tmp, path)
            except OSError:
                # 落盘失败不阻断剧情：预热池是加速器，不是事实源
                try:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                except OSError:
                    pass

    def drop(self, key: str) -> None:
        path = self._path(key)
        with self._lock:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass
