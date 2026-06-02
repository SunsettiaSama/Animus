from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .delays import calc_brew_delay_ms


@dataclass
class BrewDispatcher:
    """酝酿队列逐条 simulated 出队。"""

    emit_fn: Callable[[str, object], None]

    def drain(self, session_id: str, lines: list[str]) -> list[str]:
        sid = session_id.strip()
        delivered: list[str] = []
        for line in lines:
            text = line.strip()
            if not text:
                continue
            self._emit_brew_line(sid, text)
            delivered.append(text)
        return delivered

    def _emit_brew_line(self, session_id: str, text: str) -> None:
        from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent

        delay_ms = calc_brew_delay_ms(text)
        self.emit_fn(
            session_id,
            SpeakStreamEvent(kind="agent_typing", text="", meta={"phase": "simulated"}),
        )
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        self.emit_fn(
            session_id,
            SpeakStreamEvent(
                kind="speak",
                text=text,
                meta={
                    "phase": "simulated",
                    "tag": "speak",
                    "delivery": "simulated",
                    "brew": True,
                },
            ),
        )
        self.emit_fn(
            session_id,
            SpeakStreamEvent(
                kind="finish",
                text=text,
                final=True,
                meta={"phase": "simulated", "brew": True},
            ),
        )
