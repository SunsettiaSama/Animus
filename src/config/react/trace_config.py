from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TraceConfig:
    enabled: bool = True
    trace_dir: str = ""
    max_thought_chars: int = 0
    max_observation_chars: int = 2000

    @classmethod
    def from_dict(cls, d: dict) -> TraceConfig:
        return cls(
            enabled=bool(d.get("enabled", True)),
            trace_dir=d.get("trace_dir", ""),
            max_thought_chars=int(d.get("max_thought_chars", 0)),
            max_observation_chars=int(d.get("max_observation_chars", 2000)),
        )
