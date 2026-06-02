from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ComposeBlockId = Literal["persona", "scene", "guidance"]

KNOWN_COMPOSE_BLOCKS: tuple[ComposeBlockId, ...] = ("persona", "scene", "guidance")


@dataclass(frozen=True)
class NarrativeSlot:
    """编排块：自然叙述正文 + 域内版本号。"""

    block: ComposeBlockId
    narrative: str
    version: int

    def snapshot(self) -> dict[str, Any]:
        return {
            "block": self.block,
            "narrative": self.narrative,
            "version": self.version,
        }


@dataclass
class TurnComposeAssembly:
    """一轮 turn 的编排状态机：按固定顺序登记各块叙述与版本。"""

    session_id: str
    turn_index: int
    _slots: dict[ComposeBlockId, NarrativeSlot] = field(default_factory=dict)
    _order: list[ComposeBlockId] = field(default_factory=list)

    def set_slot(self, block: ComposeBlockId, *, narrative: str, version: int) -> None:
        slot = NarrativeSlot(
            block=block,
            narrative=narrative.strip(),
            version=version,
        )
        if block not in self._slots:
            self._order.append(block)
        self._slots[block] = slot

    def get(self, block: ComposeBlockId) -> NarrativeSlot | None:
        return self._slots.get(block)

    def slots_in_order(self) -> tuple[NarrativeSlot, ...]:
        return tuple(self._slots[b] for b in self._order if b in self._slots)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "slots": [s.snapshot() for s in self.slots_in_order()],
        }

    def attach_meta(self, meta: dict[str, Any]) -> None:
        meta["turn_compose_assembly"] = self.snapshot()
        for slot in self.slots_in_order():
            meta[f"{slot.block}_compose_version"] = slot.version
            meta[f"{slot.block}_compose_narrative_chars"] = len(slot.narrative)
