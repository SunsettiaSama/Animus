from __future__ import annotations

from dataclasses import dataclass, field

from ..fsm.state import PresenceState
from ..share_desire import ShareDesire, max_share_desire, parse_share_desire
from .events import CaptureEvent, CaptureKind
from .impulse import default_share_desire, evolution_hint


@dataclass(frozen=True)
class ShareBufferEntry:
    """一条待分享的演化捕获记录。"""

    kind: CaptureKind
    hint: str
    salience: float
    share_desire: ShareDesire
    source: str = ""
    trigger: str = ""


@dataclass(frozen=True)
class ShareFoldedPackage:
    """Gate 突破后向顶层传递的折叠分享包。"""

    summary: str
    entries: tuple[ShareBufferEntry, ...]
    peak_salience: float
    total_salience: float
    peak_share_desire: ShareDesire
    count: int

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "count": self.count,
            "peak_salience": self.peak_salience,
            "total_salience": self.total_salience,
            "peak_share_desire": self.peak_share_desire.value,
            "entries": [
                {
                    "kind": entry.kind.value,
                    "hint": entry.hint,
                    "salience": entry.salience,
                    "share_desire": entry.share_desire.value,
                    "source": entry.source,
                    "trigger": entry.trigger,
                }
                for entry in self.entries
            ],
        }


@dataclass
class ShareBuffer:
    """演化分享队列：share_desire != none 的事件在此缓冲。"""

    entries: list[ShareBufferEntry] = field(default_factory=list)

    def enqueue(self, entry: ShareBufferEntry) -> None:
        self.entries.append(entry)

    def clear(self) -> list[ShareBufferEntry]:
        drained = list(self.entries)
        self.entries.clear()
        return drained

    def __len__(self) -> int:
        return len(self.entries)


def share_entry_from_event(event: CaptureEvent) -> ShareBufferEntry | None:
    desire = parse_share_desire(
        event.payload.get("share_desire"),
        default=default_share_desire(event),
    )
    if desire == ShareDesire.none:
        return None
    hint = evolution_hint(event)
    if not hint.strip():
        return None
    payload = event.payload
    return ShareBufferEntry(
        kind=event.kind,
        hint=hint,
        salience=float(payload.get("salience", 0.0)),
        share_desire=desire,
        source=str(payload.get("source", event.kind.value)),
        trigger=str(payload.get("trigger", "")),
    )


def enqueue_share_event(buffer: ShareBuffer, event: CaptureEvent) -> bool:
    entry = share_entry_from_event(event)
    if entry is None:
        return False
    buffer.enqueue(entry)
    return True


def fold_share_buffer(
    entries: list[ShareBufferEntry],
    state: PresenceState,
) -> ShareFoldedPackage:
    if not entries:
        return ShareFoldedPackage(
            summary=state.behavior.impulse_reason,
            entries=(),
            peak_salience=0.0,
            total_salience=0.0,
            peak_share_desire=state.motivation.share_desire,
            count=0,
        )

    ordered = sorted(entries, key=lambda item: item.salience, reverse=True)
    primary = ordered[0]
    peak_desire = ShareDesire.none
    for entry in entries:
        peak_desire = max_share_desire(peak_desire, entry.share_desire)

    if len(entries) == 1:
        summary = primary.hint
    else:
        summary = f"{primary.hint}（另有 {len(entries) - 1} 条想分享的事）"

    return ShareFoldedPackage(
        summary=summary,
        entries=tuple(entries),
        peak_salience=max(item.salience for item in entries),
        total_salience=sum(item.salience for item in entries),
        peak_share_desire=peak_desire,
        count=len(entries),
    )
