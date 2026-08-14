from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.soul.speak.session.queue import UserInputItem


@dataclass
class RequestDrivenPipelineRunner:
    run_request_driven_turn: Callable[[UserInputItem], Any]

    def run(self, item: UserInputItem):
        result = self.run_request_driven_turn(item)
        result.meta["pipeline"] = "request_driven"
        if "request_driven_pipeline" not in result.notes:
            result.notes.append("request_driven_pipeline")
        return result
