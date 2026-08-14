"""Map Speak WS events to speech bubbles / talking state."""

from __future__ import annotations

from typing import Any

from agents import Agent


class SpeakPresenter:
    def __init__(self) -> None:
        self.streaming_text = ""
        self.focus: Agent | None = None
        self.busy = False
        self.last_answer = ""
        self.status = "idle"

    def bind(self, agent: Agent | None) -> None:
        self.focus = agent

    def on_message(self, msg: dict[str, Any]) -> None:
        mtype = str(msg.get("type", ""))
        if mtype == "turn_start":
            self.busy = True
            self.streaming_text = ""
            self.status = "listening"
            if self.focus is not None:
                self.focus.talking = True
            return
        if mtype == "speak_event":
            kind = str(msg.get("kind", ""))
            text = str(msg.get("text") or "")
            if kind == "speak" and text:
                self.streaming_text += text
                self.status = "talking"
                if self.focus is not None:
                    self.focus.set_bubble(self.streaming_text, ttl=8.0)
            return
        if mtype == "turn_finish":
            answer = str(msg.get("answer") or self.streaming_text or "").strip()
            self.last_answer = answer
            self.busy = False
            self.status = "idle"
            if self.focus is not None and answer:
                self.focus.set_bubble(answer, ttl=8.0)
            self.streaming_text = ""
            return
        if mtype == "error":
            self.busy = False
            self.status = "error"
            if self.focus is not None:
                self.focus.set_bubble(f"[error] {msg.get('message', '')}", ttl=5.0)
