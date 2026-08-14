from __future__ import annotations

from .types import SpeakResponderName, SpeakResponderRunner


class SpeakResponderRouter:
    def __init__(
        self,
        *,
        legacy_qa: SpeakResponderRunner,
        request_driven: SpeakResponderRunner,
        rhythm: SpeakResponderRunner,
    ) -> None:
        self._runners: dict[SpeakResponderName, SpeakResponderRunner] = {
            "legacy_qa": legacy_qa,
            "request_driven": request_driven,
            "rhythm": rhythm,
        }

    def run(self, item):
        runner = self._runners.get(item.responder)
        if runner is None:
            raise ValueError(f"unknown speak responder: {item.responder!r}")
        return runner.run(item)
