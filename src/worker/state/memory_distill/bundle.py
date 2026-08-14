"""Source bundle for the memory_distill fallback chain."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortraitSourceBundle:
    """Gathered mid/long-term memory materials for portrait derivation."""

    lines: tuple[str, ...] = ()
    unit_ids: tuple[str, ...] = ()
    medium_text: str = ""
    persona_revision: str = ""
    stable_anchor: str = ""
    source_revision: str = ""
    worker_unit_lines: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return (
            not self.lines
            and not self.medium_text.strip()
            and not self.worker_unit_lines
        )

    @property
    def medium_chars(self) -> int:
        return len(self.medium_text)
