from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptConfig:
    lang: str = "cn"
    max_question_chars: int = 0
    max_observation_chars: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> PromptConfig:
        return cls(
            lang=d.get("lang", "cn"),
            max_question_chars=int(d.get("max_question_chars", 0)),
            max_observation_chars=int(d.get("max_observation_chars", 0)),
        )
