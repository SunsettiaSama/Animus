from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaoStepRecord:
    index: int
    thought: str
    action: str
    action_input: dict
    observation: str


@dataclass
class TaoRunResult:
    answer: str
    steps: list[TaoStepRecord] = field(default_factory=list)
    step_count: int = 0

    def trace_text(self, *, tail: int = 12) -> str:
        lines: list[str] = []
        for s in self.steps[-tail:]:
            parts = [f"[{s.index}]"]
            if s.thought.strip():
                parts.append(f"思考: {s.thought.strip()[:200]}")
            if s.action.strip():
                parts.append(f"行动: {s.action}")
            if s.observation.strip():
                parts.append(f"观察: {s.observation.strip()[:200]}")
            lines.append(" | ".join(parts))
        if self.answer.strip():
            lines.append(f"[结论] {self.answer.strip()[:600]}")
        return "\n".join(lines)


@dataclass
class TaoRunRequest:
    instruction: str
    profile_name: str = "with_memory"
    system_note: str = ""


def steps_from_raw(raw_steps: list[dict]) -> list[TaoStepRecord]:
    out: list[TaoStepRecord] = []
    for s in raw_steps:
        out.append(TaoStepRecord(
            index=int(s.get("index", len(out))),
            thought=str(s.get("thought", "")),
            action=str(s.get("action", "")),
            action_input=dict(s.get("action_input") or {}),
            observation=str(s.get("observation", "")),
        ))
    return out


def result_from_runner_dict(raw: dict) -> TaoRunResult:
    steps = steps_from_raw(raw.get("steps") or [])
    return TaoRunResult(
        answer=str(raw.get("answer", "")),
        steps=steps,
        step_count=int(raw.get("step_count", len(steps))),
    )
