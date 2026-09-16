from __future__ import annotations

import re
import time
from typing import Any

from .simulation_compat import SpeakTurnPort

_BOOKING_LINE = re.compile(r"^\s*(?:预约：|【预约】)\s*(?P<text>.+?)\s*$", re.MULTILINE)
_SILENCE_ELLIPSIS = "……"


class PipelinedSpeakTurnPort(SpeakTurnPort):
    """按 responder 路由的 SpeakService 端口。

    与 speak_turing 的 SpeakServiceTurnPort 相比多了三件事：
    - responder 可选（request_driven / direct / rhythm 及消融臂别名）；
    - answer 为空时从 life_outbound 的异步交付里等一条补上
      （上次 live 跑 10 case 出现 6 条空回复，多为此因）；
    - silence_protocol（charsilence 臂）：角色可写「预约：…」行自约下一拍
      （剥出后存入 layers.EVAL_CHAR_BOOKINGS 回显）；只剩沉默时以「……」交付，
      绕开 direct 路径的空回复强制补救重试。
    """

    def __init__(
        self,
        service: Any,
        *,
        responder: str,
        life_outbound: Any,
        async_fallback_timeout_s: float = 20.0,
        label: str = "",
        silence_protocol: bool = False,
    ) -> None:
        self._service = service
        self._responder = responder
        self._label = label or responder
        self._life = life_outbound
        self._fallback_timeout_s = async_fallback_timeout_s
        self._silence_protocol = silence_protocol
        self.consumed_fallback_count = 0
        self.events: list[dict[str, Any]] = []

    @property
    def responder(self) -> str:
        return self._label

    def run_turn(self, session_id: str, user_text: str) -> str:
        orchestrator_thread = getattr(self._service, "_orchestrator_thread", None)
        if (
            orchestrator_thread is not None
            and orchestrator_thread.status()["worker"]["state"] == "stopped"
        ):
            orchestrator_thread.start()
        seen = len(self._life.recorded)
        result = self._service.run_turn(
            session_id,
            user_text,
            stream=False,
            mode="inbound",
            record=True,
            responder=self._responder,
        )
        answer = str(result.answer).strip()
        if not answer:
            answer = self._await_async_answer(session_id, seen_records=seen)
        if self._silence_protocol:
            answer = self._apply_silence_protocol(session_id, answer)
        return answer

    def _apply_silence_protocol(self, session_id: str, answer: str) -> str:
        from agent.soul.speak.responders.request_driven.layers import (
            EVAL_CHAR_BOOKINGS,
        )

        bookings = [match.group("text").strip() for match in _BOOKING_LINE.finditer(answer)]
        spoken = _BOOKING_LINE.sub("", answer).strip()
        if bookings:
            store = EVAL_CHAR_BOOKINGS.setdefault(session_id, [])
            store.extend(bookings)
            self.events.append(
                {
                    "session_id": session_id,
                    "kind": "booking",
                    "texts": bookings,
                    "spoken": spoken[:80],
                }
            )
        if not spoken:
            self.events.append(
                {"session_id": session_id, "kind": "silence", "booked": bool(bookings)}
            )
            return _SILENCE_ELLIPSIS
        if spoken in {"…", "。", ".", "……"}:
            self.events.append(
                {"session_id": session_id, "kind": "silence", "booked": bool(bookings)}
            )
            return _SILENCE_ELLIPSIS
        return spoken

    def _await_async_answer(self, session_id: str, *, seen_records: int) -> str:
        deadline = time.monotonic() + self._fallback_timeout_s
        while time.monotonic() < deadline:
            time.sleep(0.5)
            for row in self._life.recorded[seen_records:]:
                if str(row.get("session_id", "")) != session_id:
                    continue
                text = str(row.get("agent_text", "")).strip()
                if text:
                    self.consumed_fallback_count += 1
                    return text
        return ""
