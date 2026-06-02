from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class TurnInjectLedger:
    """单轮记忆注入去重：kick 仅 request，pull 仅 wait。"""

    session_id: str
    turn_index: int
    emergence_requested: bool = False
    keyword_requested: bool = False
    portrait_requested: bool = False
    notes: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "emergence_requested": self.emergence_requested,
            "keyword_requested": self.keyword_requested,
            "portrait_requested": self.portrait_requested,
            "notes": list(self.notes),
        }


class TurnInjectLedgerStore:
    def __init__(self) -> None:
        self._ledgers: dict[tuple[str, int], TurnInjectLedger] = {}
        self._lock = threading.Lock()

    def ledger(self, session_id: str, turn_index: int) -> TurnInjectLedger:
        sid = session_id.strip()
        key = (sid, turn_index)
        with self._lock:
            if key not in self._ledgers:
                self._ledgers[key] = TurnInjectLedger(session_id=sid, turn_index=turn_index)
            return self._ledgers[key]

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        with self._lock:
            drop = [k for k in self._ledgers if k[0] == sid]
            for key in drop:
                self._ledgers.pop(key, None)
