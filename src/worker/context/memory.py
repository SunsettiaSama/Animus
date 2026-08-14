from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    thought: str
    action: str         # first/only action (for finish detection + compat)
    action_input: dict  # first/only args (for compat)
    observation: str    # combined observation string (multi-call: "Observations:\n[t] → obs")
    calls: list[dict] | None = None  # [{"action": str, "args": dict}, ...] when <A> or Output:[...] used
    output: str = ""                  # <O> tag content; user-visible output for this step


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
