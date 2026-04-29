from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptConfig:
    lang: str = "cn"
    max_question_chars: int = 0
    max_observation_chars: int = 0
    repair_enabled: bool = True      # enable Layer-2 repair LLM on bad parse
    retry_on_bad_parse: int = 1      # Layer-0 retry attempts (0 = disabled)

    @classmethod
    def from_dict(cls, d: dict) -> PromptConfig:
        return cls(
            lang=d.get("lang", "cn"),
            max_question_chars=int(d.get("max_question_chars", 0)),
            max_observation_chars=int(d.get("max_observation_chars", 0)),
            repair_enabled=bool(d.get("repair_enabled", True)),
            retry_on_bad_parse=int(d.get("retry_on_bad_parse", 1)),
        )
