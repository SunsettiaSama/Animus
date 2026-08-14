from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandEntry:
    id: str
    family: str
    group: str
    name: str
    synopsis: str
    template: str
    example: str
    run_tool: str
    tags: tuple[str, ...]

    def render(self) -> str:
        tag_text = ", ".join(self.tags)
        return (
            f"{self.family}/{self.group} {self.name} — {self.synopsis} "
            f"template={self.template!r} example={self.example!r} "
            f"run_tool={self.run_tool} tags=({tag_text})"
        )


@dataclass(frozen=True)
class CommandGroup:
    family: str
    group: str
    entries: tuple[CommandEntry, ...]
