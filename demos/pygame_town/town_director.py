"""Plaza conversation director: role-framed Speak turns + JSONL log."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agents import Agent
from presenter import SpeakPresenter

OPENING_LINE = "今天天气真好，在广场碰到你真巧。"


class TownDirector:
    def __init__(
        self,
        presenter: SpeakPresenter,
        log_path: Path,
        *,
        max_rounds: int = 4,
        cooldown_s: float = 12.0,
    ) -> None:
        self.presenter = presenter
        self.log_path = log_path
        self.max_rounds = max_rounds
        self.cooldown_s = cooldown_s
        self.active = False
        self.pair: tuple[Agent, Agent] | None = None
        self.speaker_index = 0
        self.round_i = 0
        self.last_line = OPENING_LINE
        self._waiting_finish = False
        self._cooldown_until = 0.0
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _append_log(self, record: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _prompt(self, speaker: Agent, other: Agent, prior: str) -> str:
        if self.round_i == 0:
            return (
                f"[广场] 你扮演村民「{speaker.name}」，正在小镇广场。"
                f"请用一两句口语向「{other.name}」寒暄开场。只输出台词，不要解释。"
            )
        return (
            f"[广场] 你扮演村民「{speaker.name}」。"
            f"「{other.name}」对你说：「{prior}」。"
            f"只输出一句口语台词，不要解释、不要加引号。"
        )

    def maybe_start(self, plaza_agents: list[Agent], send_user_message) -> bool:
        if self.active or self._waiting_finish:
            return False
        if time.monotonic() < self._cooldown_until:
            return False
        if len(plaza_agents) < 2:
            return False
        a, b = plaza_agents[0], plaza_agents[1]
        self.pair = (a, b)
        self.speaker_index = 0
        self.round_i = 0
        self.last_line = OPENING_LINE
        self.active = True
        return self._send_next(send_user_message)

    def _send_next(self, send_user_message) -> bool:
        if self.pair is None:
            return False
        a, b = self.pair
        speaker = a if self.speaker_index == 0 else b
        other = b if self.speaker_index == 0 else a
        self.presenter.bind(speaker)
        prompt = self._prompt(speaker, other, self.last_line)
        ok = bool(send_user_message(prompt))
        self._waiting_finish = ok
        return ok

    def on_message(self, msg: dict[str, Any], send_user_message) -> None:
        if not self.active:
            return
        mtype = str(msg.get("type", ""))
        if mtype == "error":
            if not self._waiting_finish:
                return
            self._waiting_finish = False
            if self.pair is not None:
                self.pair[self.speaker_index].set_bubble(
                    f"[error] {msg.get('message', '')}",
                    ttl=5.0,
                )
            self._finish_chat()
            return
        if mtype in ("turn_start", "speak_event") and self._waiting_finish:
            self.presenter.on_message(msg)
            return
        if mtype != "turn_finish":
            return
        if not self._waiting_finish:
            return
        if bool(msg.get("server_initiated")):
            return
        self.presenter.on_message(msg)
        self._waiting_finish = False
        answer = str(msg.get("answer") or self.presenter.last_answer or "").strip()
        if not answer:
            self._finish_chat()
            return
        if self.pair is None:
            self._finish_chat()
            return
        a, b = self.pair
        speaker = a if self.speaker_index == 0 else b
        other = b if self.speaker_index == 0 else a
        speaker.set_bubble(answer, ttl=8.0)
        self._append_log(
            {
                "ts": time.time(),
                "speakers": [a.name, b.name],
                "speaker": speaker.name,
                "other": other.name,
                "round": self.round_i,
                "text": answer,
            }
        )
        self.last_line = answer
        self.round_i += 1
        self.speaker_index = 1 - self.speaker_index
        if self.round_i >= self.max_rounds:
            self._finish_chat()
            return
        self._send_next(send_user_message)

    def _finish_chat(self) -> None:
        self.active = False
        self.pair = None
        self._waiting_finish = False
        self._cooldown_until = time.monotonic() + self.cooldown_s
        self.presenter.bind(None)
