from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from config.storage import StorageConfig

_TAIL_READ_BYTES = 64 * 1024


@dataclass
class HeartbeatTickResult:
    outcome: str
    reason:  str  = ""
    duration_ms: int = 0
    detail_for_inject: str = ""


class HeartbeatTickLog:
    def __init__(self, scheduler_dir: str, *, max_bytes: int = 5_000_000) -> None:
        scheduler_dir = StorageConfig().resolve_scheduler_dir(scheduler_dir)
        self._path = os.path.join(scheduler_dir, "heartbeat_log.jsonl")
        self._rotated_path = self._path + ".1"
        self._max_bytes = max(1, int(max_bytes))
        self._lock = threading.Lock()
        os.makedirs(scheduler_dir, exist_ok=True)

    def append(self, result: HeartbeatTickResult) -> None:
        entry = {
            "ts":          datetime.now(timezone.utc).isoformat(),
            "outcome":     result.outcome,
            "reason":      result.reason,
            "duration_ms": result.duration_ms,
        }
        if result.detail_for_inject:
            entry["detail_for_inject"] = result.detail_for_inject[:8000]
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            self._rotate_if_needed(len(line.encode("utf-8")))
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)

    def recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            lines = self._read_tail()
        result = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # 坏行（如进程中途被杀截断）跳过，不允许炸掉读口
            result.append(entry)
            if len(result) >= n:
                break
        return result

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        """单代轮转：超过 max_bytes 时把当前文件挪为 .1（覆盖旧代）。

        轮转失败不阻断写日志。
        """
        try:
            size = os.path.getsize(self._path)
        except OSError:
            return
        if size + incoming_bytes <= self._max_bytes:
            return
        try:
            os.replace(self._path, self._rotated_path)
        except OSError:
            pass

    def _read_tail(self) -> list[str]:
        """只读文件尾部（64KB 窗口），不整文件加载。"""
        if not os.path.exists(self._path):
            return []
        with open(self._path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _TAIL_READ_BYTES))
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        lines = text.split("\n")
        if size > _TAIL_READ_BYTES and lines:
            lines = lines[1:]  # 丢弃可能被 seek 截断的首行
        return lines
