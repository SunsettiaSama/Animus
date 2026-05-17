from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EventCommand:
    command_type: str
    template: str
    params: dict = field(default_factory=dict)
    label: str = ""

    _VALID_TYPES = frozenset({"run_task", "ask_user", "notify_user", "chain"})

    def render(self) -> str:
        return self.template.format_map(self.params)

    def to_dict(self) -> dict:
        return {
            "command_type": self.command_type,
            "template": self.template,
            "params": self.params,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EventCommand:
        return cls(
            command_type=d.get("command_type", "run_task"),
            template=d.get("template", ""),
            params=d.get("params", {}),
            label=d.get("label", ""),
        )

    def display_label(self) -> str:
        return self.label or self.template[:40]
