from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.soul.speak.io.outbound.render_protocol import render_meta
from agent.soul.speak.io.outbound.render_time import estimate_render_time_ms
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent

if TYPE_CHECKING:
    from agent.soul.speak.io.outbound.websocket import WebSocketSpeakStreamPort

_SUPPRESS_TAGS = frozenset({"think"})


def calc_typing_delay_ms(
    text: str,
    *,
    ms_per_char: float = 12.0,
    base_ms: int = 180,
    max_ms: int = 900,
) -> int:
    """出站前短缓冲（毫秒）。

    LLM 生成阶段已有 ``agent_typing``；此处不再按全文重复计费，
    仅避免极快出稿时「秒蹦全文」。可见打字节奏主要由前端 ``phase=simulated`` 动画承担。
    """
    stripped = text.strip()
    if not stripped:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    other = max(0, len(stripped) - cjk)
    units = cjk + int(other * 0.45)
    polish = int(units * ms_per_char)
    delay = base_ms + polish
    return min(max(delay, base_ms), max_ms)


@dataclass
class _SpeakBlock:
    text: str
    delay_ms: int
    meta: dict


@dataclass
class SimulatedTypingStreamPort:
    """逐字呈现出站：thought/body/wait/silence 按序透传；speak 缓冲后下发。"""

    inner: WebSocketSpeakStreamPort
    loop: asyncio.AbstractEventLoop
    ms_per_char: float = 42.0

    _speak_buf: list[str] = field(default_factory=list)
    _in_speak: bool = False
    _pending: list[_SpeakBlock] = field(default_factory=list)
    _held_finish: SpeakStreamEvent | None = None
    _held_states: list[SpeakStreamEvent] = field(default_factory=list)
    _typing_active: bool = False

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        kind = event.kind
        meta = dict(event.meta or {})
        tag = str(meta.get("tag", ""))

        if kind == "tag" and tag in _SUPPRESS_TAGS:
            return

        if kind == "chunk":
            return

        if kind == "tag" and tag == "speak":
            self._in_speak = True
            self._speak_buf.clear()
            self._set_typing(session_id, True)
            return

        if kind == "tag" and tag == "action":
            self._in_speak = False
            self._speak_buf.clear()
            self.inner.emit(session_id, event)
            return

        if kind == "thought":
            self.inner.emit(session_id, event)
            return

        if self._in_speak and kind == "speak":
            phase = str(meta.get("phase", ""))
            piece = str(event.text or "")
            if phase == "delta":
                if piece:
                    self._speak_buf.append(piece)
                return
            if phase == "end":
                if piece:
                    self._speak_buf.append(piece)
                full = "".join(self._speak_buf).strip()
                self._speak_buf.clear()
                self._in_speak = False
                if full:
                    self._pending.append(
                        _SpeakBlock(
                            text=full,
                            delay_ms=calc_typing_delay_ms(
                                full,
                                ms_per_char=self.ms_per_char,
                            ),
                            meta=meta,
                        )
                    )
                return
            if piece:
                self._pending.append(
                    _SpeakBlock(
                        text=piece.strip(),
                        delay_ms=calc_typing_delay_ms(piece, ms_per_char=self.ms_per_char),
                        meta=meta,
                    )
                )
                self._in_speak = False
            return

        if kind == "finish":
            self._held_finish = event
            return

        if kind == "state":
            self._held_states.append(event)
            return

        if kind == "action":
            self.inner.emit(session_id, event)
            return

        if kind == "speak":
            full = str(event.text or "").strip()
            if not full:
                return
            # 角色时间线已带 typing + render_target，成对透传，避免二次缓冲抢走 body 转圈
            if str(meta.get("render_target") or "").strip().lower() == "speak":
                self.inner.emit(session_id, event)
                return
            self._set_typing(session_id, True)
            self._pending.append(
                _SpeakBlock(
                    text=full,
                    delay_ms=calc_typing_delay_ms(full, ms_per_char=self.ms_per_char),
                    meta=meta,
                )
            )
            return

        self.inner.emit(session_id, event)

    async def flush_pending(self, session_id: str) -> None:
        for block in self._pending:
            if block.delay_ms > 0:
                await asyncio.sleep(block.delay_ms / 1000.0)
            prior = dict(block.meta or {})
            wait_ms = int(prior.get("wait_ms") or prior.get("render_time_ms") or 0)
            if wait_ms <= 0:
                wait_ms = estimate_render_time_ms(block.text)
            speak_meta = render_meta(
                "speak",
                phase="simulated",
                wait_ms=wait_ms,
                extra={
                    **prior,
                    "tag": "speak",
                    "delivery": "simulated",
                    "render_time_ms": wait_ms,
                    "render_target": "speak",
                },
            )
            self.inner.emit(
                session_id,
                SpeakStreamEvent(
                    kind="speak",
                    text=block.text,
                    meta=speak_meta,
                ),
            )
        self._pending.clear()
        self._set_typing(session_id, False)

        held_states = list(self._held_states)
        self._held_states.clear()
        for state in held_states:
            self.inner.emit(session_id, state)

        if self._held_finish is not None:
            finish = self._held_finish
            self._held_finish = None
            self.inner.emit(session_id, finish)

    def _set_typing(self, session_id: str, active: bool) -> None:
        if self._typing_active == active:
            return
        self._typing_active = active
        self.inner.emit(
            session_id,
            SpeakStreamEvent(
                kind="agent_typing",
                text="",
                meta=render_meta(
                    "typing",
                    extra={"active": active, "delivery": "simulated"},
                ),
            ),
        )

    def close(self) -> None:
        self.inner.close()
