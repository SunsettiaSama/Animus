from __future__ import annotations

from typing import Any, Literal, Protocol

SpeakResponderName = Literal["legacy_qa", "request_driven", "rhythm", "direct"]
DEFAULT_SPEAK_RESPONDER: SpeakResponderName = "request_driven"


def normalize_speak_responder(value: str | None) -> SpeakResponderName:
    if value is None:
        return DEFAULT_SPEAK_RESPONDER
    normalized = value.strip().lower()
    if not normalized:
        return DEFAULT_SPEAK_RESPONDER
    if normalized == "request_driven":
        return "request_driven"
    if normalized == "rhythm":
        return "rhythm"
    if normalized == "direct":
        return "direct"
    raise ValueError(f"unknown speak responder: {value!r}")


class SpeakResponderRunner(Protocol):
    def run(self, item: Any) -> Any: ...
