from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryBlock:
    label: str = "记忆"
    entries: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.entries:
            return ""
        body = "\n".join(f"- {e}" for e in self.entries)
        return f"[{self.label}]\n{body}"

    def is_empty(self) -> bool:
        return not self.entries
