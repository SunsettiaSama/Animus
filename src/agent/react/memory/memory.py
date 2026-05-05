from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    thought: str
    action: str
    action_input: dict
    observation: str


class Memory:
    def __init__(self):
        self._steps: list[Step] = []

    def add(self, step: Step) -> None:
        self._steps.append(step)

    def steps(self) -> list[Step]:
        return list(self._steps)

    def clear(self) -> None:
        self._steps.clear()

    def __len__(self) -> int:
        return len(self._steps)
