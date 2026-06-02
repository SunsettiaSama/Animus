from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LingeringMood:
    text: str
    until_iso: str
    source_unit_id: str = ""

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "until_iso": self.until_iso,
            "source_unit_id": self.source_unit_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LingeringMood:
        return cls(
            text=str(d.get("text", "")),
            until_iso=str(d.get("until_iso", "")),
            source_unit_id=str(d.get("source_unit_id", "")),
        )


@dataclass
class RecentExperiencePortrait:
    narrative: str = ""
    distilled_at: str = ""
    source_unit_ids: list[str] = field(default_factory=list)
    last_distilled_unit_id: str = ""

    def to_dict(self) -> dict:
        return {
            "narrative": self.narrative,
            "distilled_at": self.distilled_at,
            "source_unit_ids": list(self.source_unit_ids),
            "last_distilled_unit_id": self.last_distilled_unit_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RecentExperiencePortrait:
        return cls(
            narrative=str(d.get("narrative", "")),
            distilled_at=str(d.get("distilled_at", "")),
            source_unit_ids=[str(x) for x in (d.get("source_unit_ids") or [])],
            last_distilled_unit_id=str(d.get("last_distilled_unit_id", "")),
        )
