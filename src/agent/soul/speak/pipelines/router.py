from __future__ import annotations

from .types import SpeakPipelineName, SpeakPipelineRunner


class SpeakPipelineRouter:
    def __init__(
        self,
        *,
        legacy_qa: SpeakPipelineRunner,
        request_driven: SpeakPipelineRunner,
    ) -> None:
        self._runners: dict[SpeakPipelineName, SpeakPipelineRunner] = {
            "legacy_qa": legacy_qa,
            "request_driven": request_driven,
        }

    def run(self, item):
        runner = self._runners.get(item.pipeline)
        if runner is None:
            raise ValueError(f"unknown speak pipeline: {item.pipeline!r}")
        return runner.run(item)
