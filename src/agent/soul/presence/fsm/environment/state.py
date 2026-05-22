from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EnvironmentState:
    """环境与背景：场景、社交模式与环境刺激。"""

    setting: str = ""
    context: str = ""
    social_mode: str = ""
    stimuli: list[str] = field(default_factory=list)

    def copy(self) -> EnvironmentState:
        return EnvironmentState(
            setting=self.setting,
            context=self.context,
            social_mode=self.social_mode,
            stimuli=list(self.stimuli),
        )

    def to_dict(self) -> dict:
        return {
            "setting": self.setting,
            "context": self.context,
            "social_mode": self.social_mode,
            "stimuli": list(self.stimuli),
        }

    @classmethod
    def from_dict(cls, d: dict) -> EnvironmentState:
        return cls(
            setting=str(d.get("setting", "")),
            context=str(d.get("context", "")),
            social_mode=str(d.get("social_mode", "")),
            stimuli=[str(s) for s in d.get("stimuli", [])],
        )
