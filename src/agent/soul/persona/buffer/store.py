from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config.storage import StorageConfig

from .buffer import ExperienceBuffer
from .trace import ClusterSignal

_SIGNALS_FILENAME = "experience_buffer.jsonl"
_META_FILENAME = "buffer_meta.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BufferMeta:
    """Buffer 调度元数据（非记忆内容）。"""

    last_drift_at: str = ""
    last_drift_month: str = ""

    def to_dict(self) -> dict:
        return {
            "last_drift_at": self.last_drift_at,
            "last_drift_month": self.last_drift_month,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BufferMeta:
        return cls(
            last_drift_at=str(
                d.get("last_drift_at", d.get("last_monthly_update_at", ""))
            ),
            last_drift_month=str(
                d.get("last_drift_month", d.get("last_monthly_update_month", ""))
            ),
        )


@dataclass
class BufferState:
    buffer: ExperienceBuffer = field(default_factory=ExperienceBuffer)
    meta: BufferMeta = field(default_factory=BufferMeta)


class ExperienceBufferStore:
    """Persona buffer 持久化：信号 jsonl + 调度 meta。"""

    def __init__(self, persona_dir: str) -> None:
        persona_dir = StorageConfig().resolve_persona_dir(persona_dir)
        self._dir = Path(persona_dir)
        self._signals_path = self._dir / _SIGNALS_FILENAME
        self._meta_path = self._dir / _META_FILENAME

    def load(self) -> ExperienceBuffer:
        return self.load_state().buffer

    def load_meta(self) -> BufferMeta:
        return self.load_state().meta

    def load_state(self) -> BufferState:
        signals: list[ClusterSignal] = []
        if self._signals_path.exists():
            with open(self._signals_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    signals.append(ClusterSignal.from_dict(json.loads(line)))
        meta = BufferMeta()
        if self._meta_path.exists():
            with open(self._meta_path, encoding="utf-8") as f:
                meta = BufferMeta.from_dict(json.load(f))
        return BufferState(buffer=ExperienceBuffer(signals), meta=meta)

    def save(self, buffer: ExperienceBuffer) -> None:
        self.save_state(BufferState(buffer=buffer, meta=self.load_meta()))

    def save_meta(self, meta: BufferMeta) -> None:
        state = self.load_state()
        state.meta = meta
        self.save_state(state)

    def save_state(self, state: BufferState) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._signals_path, "w", encoding="utf-8") as f:
            for item in state.buffer.to_dicts():
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(state.meta.to_dict(), f, ensure_ascii=False, indent=2)

    def append(self, signal: ClusterSignal) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._signals_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(signal.to_dict(), ensure_ascii=False) + "\n")

    def touch_drift_run(self, month: str, *, at: str | None = None) -> BufferMeta:
        meta = self.load_meta()
        meta.last_drift_month = month
        meta.last_drift_at = at or _now_iso()
        self.save_meta(meta)
        return meta

    def clear(self) -> None:
        if self._signals_path.exists():
            self._signals_path.unlink()
        if self._meta_path.exists():
            self._meta_path.unlink()
