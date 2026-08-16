from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

AgendaSource = Literal["director", "character"]
AgendaKind = Literal["speak", "silence"]

BOOKING_GAP_MU_SEC = 25.0
BOOKING_GAP_SIGMA_SEC = 6.0
BOOKING_GAP_MIN_SEC = 25.0


def sample_booking_gap_sec(*, rng: random.Random | None = None) -> float:
    """高斯抽样间隔：均值 25s，结果不得小于 25s。"""
    sampler = rng if rng is not None else random
    return max(BOOKING_GAP_MIN_SEC, float(sampler.gauss(BOOKING_GAP_MU_SEC, BOOKING_GAP_SIGMA_SEC)))


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@dataclass
class AgendaEntry:
    """开口/沉默预约条目。source=director 优先于 character。"""

    at: float
    kind: AgendaKind = "speak"
    source: AgendaSource = "character"
    entry_id: str = ""
    plot_unit_id: str = ""
    reason: str = ""
    end_at: float | None = None
    duration_sec: float = 0.0
    status: Literal["pending", "fired", "cancelled"] = "pending"

    def __post_init__(self) -> None:
        if not str(self.entry_id or "").strip():
            self.entry_id = _new_id("agenda")
        kind = str(self.kind or "speak").strip().lower()
        self.kind = "silence" if kind == "silence" else "speak"  # type: ignore[assignment]
        source = str(self.source or "character").strip().lower()
        self.source = "director" if source == "director" else "character"  # type: ignore[assignment]
        status = str(self.status or "pending").strip().lower()
        if status not in ("pending", "fired", "cancelled"):
            status = "pending"
        self.status = status  # type: ignore[assignment]
        self.plot_unit_id = str(self.plot_unit_id or "").strip()
        self.reason = str(self.reason or "").strip()[:240]
        self.at = float(self.at or 0.0)
        self.duration_sec = max(0.0, float(self.duration_sec or 0.0))
        if self.end_at is not None:
            self.end_at = float(self.end_at)

    def snapshot(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "at": float(self.at),
            "kind": self.kind,
            "source": self.source,
            "plot_unit_id": self.plot_unit_id,
            "reason": self.reason,
            "end_at": self.end_at,
            "duration_sec": float(self.duration_sec),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AgendaEntry | None:
        if not isinstance(data, dict):
            return None
        if data.get("at") is None:
            return None
        end_raw = data.get("end_at")
        return cls(
            entry_id=str(data.get("entry_id") or "").strip(),
            at=float(data.get("at") or 0.0),
            kind=str(data.get("kind") or "speak"),  # type: ignore[arg-type]
            source=str(data.get("source") or "character"),  # type: ignore[arg-type]
            plot_unit_id=str(data.get("plot_unit_id") or "").strip(),
            reason=str(data.get("reason") or "").strip(),
            end_at=float(end_raw) if end_raw is not None else None,
            duration_sec=float(data.get("duration_sec") or 0.0),
            status=str(data.get("status") or "pending"),  # type: ignore[arg-type]
        )


@dataclass
class CharacterSpeakAgenda:
    """可管理开口时间轴：导演戳优先，角色预约其次；写入统一过间隔硬闸。"""

    entries: list[AgendaEntry] = field(default_factory=list)
    last_event_at: float = 0.0
    last_duration_sec: float = 0.0
    revised_at: float = 0.0
    version: int = 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "revised_at": float(self.revised_at),
            "last_event_at": float(self.last_event_at),
            "last_duration_sec": float(self.last_duration_sec),
            "entries": [e.snapshot() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CharacterSpeakAgenda:
        if not isinstance(data, dict):
            return cls()
        entries: list[AgendaEntry] = []
        raw = data.get("entries")
        if isinstance(raw, list):
            for item in raw:
                entry = AgendaEntry.from_dict(item if isinstance(item, dict) else None)
                if entry is not None:
                    entries.append(entry)
        return cls(
            entries=entries,
            last_event_at=float(data.get("last_event_at") or 0.0),
            last_duration_sec=float(data.get("last_duration_sec") or 0.0),
            revised_at=float(data.get("revised_at") or 0.0),
            version=max(1, int(data.get("version") or 1)),
        )

    def note_event(self, at: float | None = None, *, duration_sec: float = 0.0) -> None:
        self.last_event_at = float(time.time() if at is None else at)
        held = max(0.0, float(duration_sec or 0.0))
        if held > 0:
            self.last_duration_sec = held

    def _anchor_entry(self) -> AgendaEntry | None:
        pending = [e for e in self.entries if e.status == "pending"]
        if not pending:
            return None
        return max(pending, key=lambda e: float(e.at))

    def _anchor_at(self) -> float:
        last = float(self.last_event_at or 0.0)
        entry = self._anchor_entry()
        if entry is not None:
            return max(last, float(entry.at))
        return last if last > 0 else time.time()

    def _anchor_duration_sec(self) -> float:
        entry = self._anchor_entry()
        if entry is not None:
            return max(0.0, float(entry.duration_sec or 0.0))
        return max(0.0, float(self.last_duration_sec or 0.0))

    def enforce_gap(
        self,
        proposed_at: float,
        *,
        rng: random.Random | None = None,
    ) -> float:
        """抬到上一开口 + max(硬间隔, 上一动作做完所需秒数)。"""
        gap = max(sample_booking_gap_sec(rng=rng), self._anchor_duration_sec())
        floor = self._anchor_at() + gap
        return max(float(proposed_at), floor)

    def add_speak(
        self,
        *,
        at: float,
        source: AgendaSource,
        plot_unit_id: str = "",
        reason: str = "",
        duration_sec: float = 0.0,
        rng: random.Random | None = None,
        enforce: bool = True,
    ) -> AgendaEntry:
        stamped = self.enforce_gap(at, rng=rng) if enforce else float(at)
        if source == "character":
            stamped = self._yield_to_director(stamped)
        entry = AgendaEntry(
            at=stamped,
            kind="speak",
            source=source,
            plot_unit_id=plot_unit_id,
            reason=reason,
            duration_sec=duration_sec,
        )
        self.entries.append(entry)
        self.revised_at = time.time()
        self.version = int(self.version) + 1
        return entry

    def add_silence(
        self,
        *,
        start: float,
        end: float,
        source: AgendaSource,
        plot_unit_id: str = "",
        reason: str = "",
        duration_sec: float = 0.0,
        rng: random.Random | None = None,
        enforce: bool = True,
    ) -> AgendaEntry:
        stamped = self.enforce_gap(start, rng=rng) if enforce else float(start)
        if source == "character":
            stamped = self._yield_to_director(stamped)
        held = max(0.0, float(duration_sec or 0.0))
        end_at = max(float(end), stamped + held)
        entry = AgendaEntry(
            at=stamped,
            end_at=end_at,
            kind="silence",
            source=source,
            plot_unit_id=plot_unit_id,
            reason=reason,
            duration_sec=held or max(0.0, end_at - stamped),
        )
        self.entries.append(entry)
        self.revised_at = time.time()
        self.version = int(self.version) + 1
        return entry

    def _yield_to_director(self, at: float) -> float:
        """角色预约撞上导演 pending 戳时让到导演之后。"""
        director_pending = [
            e
            for e in self.entries
            if e.status == "pending" and e.source == "director" and e.kind == "speak"
        ]
        if not director_pending:
            return float(at)
        nearest = min(director_pending, key=lambda e: abs(float(e.at) - float(at)))
        # 同窗冲突：角色让到导演戳之后再加一个硬下限
        if abs(float(nearest.at) - float(at)) < BOOKING_GAP_MIN_SEC:
            return float(nearest.at) + sample_booking_gap_sec()
        return float(at)

    def due_entries(self, *, now: float | None = None) -> list[AgendaEntry]:
        current = time.time() if now is None else float(now)
        due = [
            e
            for e in self.entries
            if e.status == "pending" and e.kind == "speak" and float(e.at) <= current
        ]
        # 导演优先
        due.sort(key=lambda e: (0 if e.source == "director" else 1, float(e.at)))
        return due

    def peek_due(self, *, now: float | None = None) -> AgendaEntry | None:
        due = self.due_entries(now=now)
        return due[0] if due else None

    def mark_fired(self, entry_id: str) -> AgendaEntry | None:
        eid = str(entry_id or "").strip()
        for entry in self.entries:
            if entry.entry_id == eid and entry.status == "pending":
                entry.status = "fired"
                self.note_event(entry.at, duration_sec=entry.duration_sec)
                self.revised_at = time.time()
                return entry
        return None

    def cancel_character_overlapping(self, *, around: float, window_sec: float = 25.0) -> int:
        cancelled = 0
        for entry in self.entries:
            if entry.status != "pending" or entry.source != "character":
                continue
            if abs(float(entry.at) - float(around)) <= float(window_sec):
                entry.status = "cancelled"
                cancelled += 1
        if cancelled:
            self.revised_at = time.time()
            self.version = int(self.version) + 1
        return cancelled

    def render_for_director(self) -> str:
        lines = [
            "[开口议程｜导演戳优先]",
            f"version={self.version} last_event_at={self.last_event_at:.3f}",
        ]
        pending = [e for e in self.entries if e.status == "pending"]
        if not pending:
            lines.append("（无 pending）")
            return "\n".join(lines)
        for entry in sorted(pending, key=lambda e: (0 if e.source == "director" else 1, e.at)):
            eta = max(0.0, float(entry.at) - time.time())
            held = float(entry.duration_sec or 0.0)
            hold = f" 动作约{held:.0f}s" if held > 0 else ""
            lines.append(
                f"- [{entry.source}/{entry.kind}] id={entry.entry_id} "
                f"at={entry.at:.3f}(+{eta:.1f}s){hold} plot={entry.plot_unit_id or '—'} "
                f"reason={entry.reason or '—'}"
            )
        return "\n".join(lines)
