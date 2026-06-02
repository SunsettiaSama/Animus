from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..events import SpeakStreamEvent

_HOLD_KINDS = frozenset({"speak", "chunk"})


@dataclass
class SpeakTypingHoldEmitter:
    """Flush 出站持有：生成期不向端口推送 speak/chunk，finish 时以 simulated 一次下发。"""

    inner: Callable[[str, SpeakStreamEvent], None]
    enabled: bool = True
    _pending: list[tuple[str, SpeakStreamEvent]] = field(default_factory=list)

    def __call__(self, session_id: str, event: SpeakStreamEvent) -> None:
        if not self.enabled:
            self.inner(session_id, event)
            return

        kind = event.kind
        if kind in _HOLD_KINDS:
            self._pending.append((session_id, event))
            return

        if kind == "finish":
            self._flush_pending(session_id)
            self.inner(session_id, event)
            return

        self.inner(session_id, event)

    def _flush_pending(self, session_id: str) -> None:
        remaining: list[tuple[str, SpeakStreamEvent]] = []
        for sid, event in self._pending:
            if sid != session_id:
                remaining.append((sid, event))
                continue
            text = str(event.text or "").strip()
            if not text:
                continue
            meta = dict(event.meta or {})
            meta.setdefault("phase", "simulated")
            meta.setdefault("tag", "speak")
            meta.setdefault("delivery", "simulated")
            self.inner(
                sid,
                SpeakStreamEvent(kind="speak", text=text, meta=meta),
            )
        self._pending = remaining

    def reset_session(self, session_id: str) -> None:
        sid = session_id.strip()
        self._pending = [(s, e) for s, e in self._pending if s != sid]
