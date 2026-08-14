from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..guidance.control import GuidanceControlState
else:
    GuidanceControlState = Any  # type: ignore[assignment,misc]

BlockId = Literal[
    "system",
    "persona",
    "scene",
    "guidance",
    "context",
    "memory",
    "social",
    "share",
]

KNOWN_BLOCKS: tuple[BlockId, ...] = (
    "system",
    "persona",
    "scene",
    "guidance",
    "context",
    "memory",
    "social",
    "share",
)

VERSIONED_BLOCKS: tuple[BlockId, ...] = ("persona", "scene", "guidance")

BlockPhase = Literal["kick", "refresh", "apply", "post_turn"]

REFRESH_ORDER: tuple[BlockId, ...] = (
    "system",
    "persona",
    "scene",
    "share",
    "guidance",
    "context",
)


@dataclass(frozen=True)
class BlockSnapshot:
    block: BlockId
    summary: str
    version: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BlockSlot:
    block: BlockId
    narrative: str
    version: int

    def snapshot(self) -> dict[str, Any]:
        return {
            "block": self.block,
            "narrative": self.narrative,
            "version": self.version,
        }


@dataclass
class TurnBlockAssembly:
    session_id: str
    turn_index: int
    _slots: dict[BlockId, BlockSlot] = field(default_factory=dict)
    _order: list[BlockId] = field(default_factory=list)

    def set_slot(self, block: BlockId, *, narrative: str, version: int) -> None:
        slot = BlockSlot(block=block, narrative=narrative.strip(), version=version)
        if block not in self._slots:
            self._order.append(block)
        self._slots[block] = slot

    def get(self, block: BlockId) -> BlockSlot | None:
        return self._slots.get(block)

    def slots_in_order(self) -> tuple[BlockSlot, ...]:
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


@dataclass(frozen=True)
class BlockVersionLedger:
    persona: int | None = None
    scene: int | None = None
    guidance: int | None = None
    turn_index: int | None = None
    generation: int | None = None

    def get(self, block: BlockId) -> int | None:
        if block not in VERSIONED_BLOCKS:
            return None
        return getattr(self, block)

    def snapshot(self) -> dict[str, object]:
        return {
            "persona": self.persona,
            "scene": self.scene,
            "guidance": self.guidance,
            "turn_index": self.turn_index,
            "generation": self.generation,
        }


@dataclass
class PlanSidecar:
    control_snapshot: GuidanceControlState | None = None
    recall_candidates: tuple[Any, ...] = ()
    recall_preview: str = ""
    interactor_portrait: str = ""
