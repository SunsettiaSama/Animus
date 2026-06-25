from __future__ import annotations

from typing import Any, Literal, Protocol

SpeakPipelineName = Literal["legacy_qa", "request_driven"]
DEFAULT_SPEAK_PIPELINE: SpeakPipelineName = "legacy_qa"


def normalize_speak_pipeline(value: str | None) -> SpeakPipelineName:
    if value is None:
        return DEFAULT_SPEAK_PIPELINE
    normalized = value.strip().lower()
    if not normalized:
        return DEFAULT_SPEAK_PIPELINE
    if normalized == "legacy_qa":
        return "legacy_qa"
    if normalized == "request_driven":
        return "request_driven"
    raise ValueError(f"unknown speak pipeline: {value!r}")


class SpeakPipelineRunner(Protocol):
    def run(self, item: Any) -> Any: ...
