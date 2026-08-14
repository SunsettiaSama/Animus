from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "workbench" / "speak_turing"
DEFAULT_CASES_PATH = DEFAULT_DATA_DIR / "cases.jsonl"
DEFAULT_MANIFEST_PATH = DEFAULT_DATA_DIR / "manifest.json"

_DIFFICULTIES = {"easy", "medium", "hard"}


@dataclass(frozen=True)
class UserPersona:
    age_range: str
    occupation: str
    traits: tuple[str, ...]
    communication_style: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "UserPersona":
        traits = raw.get("traits")
        if not isinstance(traits, list) or not traits:
            raise ValueError("persona.traits must be a non-empty list")
        persona = cls(
            age_range=str(raw.get("age_range", "")).strip(),
            occupation=str(raw.get("occupation", "")).strip(),
            traits=tuple(str(item).strip() for item in traits if str(item).strip()),
            communication_style=str(raw.get("communication_style", "")).strip(),
        )
        if not all((persona.age_range, persona.occupation, persona.communication_style)):
            raise ValueError("persona fields must not be empty")
        return persona

    def to_dict(self) -> dict[str, Any]:
        return {
            "age_range": self.age_range,
            "occupation": self.occupation,
            "traits": list(self.traits),
            "communication_style": self.communication_style,
        }


@dataclass(frozen=True)
class SpeakTuringCase:
    case_id: str
    persona: UserPersona
    relationship: str
    goal: str
    opening: str
    emotion: str
    topic: str
    difficulty: str
    turns: int
    tags: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SpeakTuringCase":
        required = {
            "case_id",
            "persona",
            "relationship",
            "goal",
            "opening",
            "emotion",
            "topic",
            "difficulty",
            "turns",
            "tags",
        }
        missing = required.difference(raw)
        if missing:
            raise ValueError(f"speak turing case missing fields: {sorted(missing)}")
        persona_raw = raw["persona"]
        if not isinstance(persona_raw, dict):
            raise ValueError("persona must be an object")
        tags_raw = raw["tags"]
        if not isinstance(tags_raw, list) or not tags_raw:
            raise ValueError("tags must be a non-empty list")
        difficulty = str(raw["difficulty"]).strip().lower()
        if difficulty not in _DIFFICULTIES:
            raise ValueError(f"unsupported difficulty: {difficulty!r}")
        turns = int(raw["turns"])
        if turns < 4 or turns > 6:
            raise ValueError("turns must be between 4 and 6")
        case = cls(
            case_id=str(raw["case_id"]).strip(),
            persona=UserPersona.from_dict(persona_raw),
            relationship=str(raw["relationship"]).strip(),
            goal=str(raw["goal"]).strip(),
            opening=str(raw["opening"]).strip(),
            emotion=str(raw["emotion"]).strip(),
            topic=str(raw["topic"]).strip(),
            difficulty=difficulty,
            turns=turns,
            tags=tuple(str(item).strip() for item in tags_raw if str(item).strip()),
        )
        if not case.case_id or not case.tags:
            raise ValueError("case_id and tags must not be empty")
        if not all((case.relationship, case.goal, case.opening, case.emotion, case.topic)):
            raise ValueError(f"case {case.case_id!r} contains empty metadata")
        return case

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "persona": self.persona.to_dict(),
            "relationship": self.relationship,
            "goal": self.goal,
            "opening": self.opening,
            "emotion": self.emotion,
            "topic": self.topic,
            "difficulty": self.difficulty,
            "turns": self.turns,
            "tags": list(self.tags),
        }


def parse_jsonl(text: str) -> list[SpeakTuringCase]:
    cases: list[SpeakTuringCase] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: root must be an object")
        case = SpeakTuringCase.from_dict(payload)
        if case.case_id in seen:
            raise ValueError(f"line {line_number}: duplicate case_id {case.case_id!r}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("speak turing dataset is empty")
    return cases


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[SpeakTuringCase]:
    return parse_jsonl(path.read_text(encoding="utf-8"))
