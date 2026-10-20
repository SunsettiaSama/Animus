"""MemoryTelemetry：记忆事件流水（append-only JSONL + 异步落盘）。

设计约束（PRD R1 / 2.4"观测不改变行为"）：
- ``emit`` 只做"构造 dict + 入队"，全部异常内吞，永不 raise、永不阻塞；
- 队列满丢最旧并计数，不允许反压到检索/写入主链路；
- 单代轮转 + 坏行容忍的读口，复用 ``HeartbeatTickLog`` 已验证的模式；
- ``enabled=False`` 时 ``get_memory_telemetry()`` 返回 None，零事件、零对象。
"""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from agent.soul.memory.telemetry.config import MemoryTelemetryConfig

_DRAIN_POLL_SEC = 0.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryTelemetry:
    def __init__(self, cfg: MemoryTelemetryConfig) -> None:
        self._cfg = cfg
        self._path = cfg.events_path
        self._rotated_path = Path(str(self._path) + ".1")
        self._lock = threading.Lock()
        self._pending: deque[dict] = deque()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._emitted = 0
        self._written = 0
        self._dropped = 0
        self._thread: threading.Thread | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def config(self) -> MemoryTelemetryConfig:
        return self._cfg

    # ── 生产侧（调用方永不感知失败） ────────────────────────────────────────

    def emit(self, event: str, **fields) -> None:
        try:
            if self._stop.is_set() or not event:
                return
            entry = {"ts": _now_iso(), "event": event}
            entry.update(fields)
            with self._lock:
                if len(self._pending) >= self._cfg.queue_size:
                    self._pending.popleft()
                    self._dropped += 1
                self._pending.append(entry)
                self._emitted += 1
            self._start_thread()
            self._wake.set()
        except Exception:
            pass

    # ── 消费侧（后台单线程） ────────────────────────────────────────────────

    def _start_thread(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="memory-telemetry"
            )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(_DRAIN_POLL_SEC)
            self._wake.clear()
            self._drain()
        self._drain()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                batch = list(self._pending)
                self._pending.clear()
            try:
                self._write_batch(batch)
            except Exception:
                # 落盘失败：丢本批并计数，不允许炸线程或反压
                with self._lock:
                    self._dropped += len(batch)

    def _write_batch(self, batch: list[dict]) -> None:
        lines = "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in batch)
        payload = lines.encode("utf-8")
        self._rotate_if_needed(len(payload))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(lines)
        with self._lock:
            self._written += len(batch)

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        """单代轮转：超过 max_events_bytes 挪为 .1（覆盖旧代）。失败不阻断写。"""
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        if size + incoming_bytes <= self._cfg.max_events_bytes:
            return
        try:
            self._rotated_path.unlink(missing_ok=True)
            self._path.replace(self._rotated_path)
        except OSError:
            pass

    # ── 快照（同步写；调用点在 memory/sleep worker，低频） ──────────────────

    def write_snapshot(self, snapshot: dict) -> Path:
        ts = str(snapshot.get("ts") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
        # Windows 文件名安全：仅保留字母数字与 - _
        safe = "".join(c if (c.isalnum() or c == "-") else "_" for c in ts)
        self._cfg.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self._cfg.snapshot_dir / f"{safe}_growth_snapshot.json"
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )
        self.emit(
            "snapshot_taken",
            path=str(path),
            node_count=snapshot.get("node_count"),
            edge_count=snapshot.get("edge_count"),
        )
        return path

    # ── 读口 / 生命周期 ────────────────────────────────────────────────────

    def iter_events(self, path: Path | None = None) -> Iterator[dict]:
        """按序读事件（含轮转旧代在前的完整历史）；坏行跳过。"""
        target = path or self._path
        for p in (self._rotated_path if target == self._path else None, target):
            if p is None or not p.exists():
                continue
            with open(p, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue

    def flush(self, timeout: float = 5.0) -> None:
        """排空队列（测试/停机前用）。"""
        deadline = datetime.now(timezone.utc).timestamp() + max(0.0, timeout)
        while datetime.now(timezone.utc).timestamp() < deadline:
            with self._lock:
                pending = len(self._pending)
            if pending == 0 and self._thread is not None:
                return
            if pending == 0 and self._thread is None:
                return
            self._wake.set()
            threading.Event().wait(0.02)

    def close(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def stats(self) -> dict:
        with self._lock:
            return {
                "enabled": self._cfg.enabled,
                "path": str(self._path),
                "emitted": self._emitted,
                "written": self._written,
                "dropped": self._dropped,
                "pending": len(self._pending),
                "running": self._thread is not None,
            }
