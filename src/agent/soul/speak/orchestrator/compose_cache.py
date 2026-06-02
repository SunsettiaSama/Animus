from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .compose_reconcile import ComposeVersionLedger, read_bundle_ledger
from .compose_slots import ComposeBlockId, KNOWN_COMPOSE_BLOCKS, TurnComposeAssembly


@dataclass(frozen=True)
class ComposeModuleCacheEntry:
    block: ComposeBlockId
    narrative: str
    version: int
    updated_monotonic: float

    def snapshot(self) -> dict[str, object]:
        return {
            "block": self.block,
            "narrative": self.narrative,
            "version": self.version,
            "updated_monotonic": self.updated_monotonic,
        }


@dataclass
class SessionComposeCache:
    """Orchestrator 侧各编排块的叙述缓存与版本台账。"""

    session_id: str
    ledger: ComposeVersionLedger = field(default_factory=ComposeVersionLedger)
    slots: dict[ComposeBlockId, ComposeModuleCacheEntry] = field(default_factory=dict)
    sync_notes: list[str] = field(default_factory=list)

    def meta_snapshot(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "compose_session_turn": self.ledger.turn_index,
            "compose_session_generation": self.ledger.generation,
        }
        assembly_slots: list[dict[str, object]] = []
        for block in KNOWN_COMPOSE_BLOCKS:
            entry = self.slots.get(block)
            if entry is None:
                continue
            assembly_slots.append(
                {
                    "block": entry.block,
                    "narrative": entry.narrative,
                    "version": entry.version,
                }
            )
            meta[f"{block}_compose_version"] = entry.version
            meta[f"{block}_compose_narrative_chars"] = len(entry.narrative)
        if assembly_slots:
            meta["turn_compose_assembly"] = {
                "session_id": self.session_id,
                "turn_index": self.ledger.turn_index,
                "slots": assembly_slots,
            }
        return meta

    def update_from_meta(self, meta: dict[str, Any]) -> None:
        self.ledger = read_bundle_ledger(meta)
        assembly = meta.get("turn_compose_assembly")
        if not isinstance(assembly, dict):
            return
        slots = assembly.get("slots")
        if not isinstance(slots, list):
            return
        now = time.monotonic()
        for raw in slots:
            if not isinstance(raw, dict):
                continue
            block = raw.get("block")
            version = raw.get("version")
            narrative = raw.get("narrative")
            if block not in KNOWN_COMPOSE_BLOCKS:
                continue
            if not isinstance(version, int):
                continue
            text = narrative.strip() if isinstance(narrative, str) else ""
            self.slots[block] = ComposeModuleCacheEntry(
                block=block,
                narrative=text,
                version=version,
                updated_monotonic=now,
            )

    def update_from_assembly(self, assembly: TurnComposeAssembly, *, generation: int | None = None) -> None:
        self.ledger = ComposeVersionLedger(
            persona=assembly.get("persona").version if assembly.get("persona") else None,
            scene=assembly.get("scene").version if assembly.get("scene") else None,
            guidance=assembly.get("guidance").version if assembly.get("guidance") else None,
            turn_index=assembly.turn_index,
            generation=generation if generation is not None else self.ledger.generation,
        )
        now = time.monotonic()
        for slot in assembly.slots_in_order():
            self.slots[slot.block] = ComposeModuleCacheEntry(
                block=slot.block,
                narrative=slot.narrative,
                version=slot.version,
                updated_monotonic=now,
            )

    def snapshot(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "ledger": self.ledger.snapshot(),
            "slots": [entry.snapshot() for entry in self.slots.values()],
        }


class ComposeCacheRegistry:
    def __init__(self) -> None:
        self._caches: dict[str, SessionComposeCache] = {}

    def get(self, session_id: str) -> SessionComposeCache:
        sid = session_id.strip()
        if sid not in self._caches:
            self._caches[sid] = SessionComposeCache(session_id=sid)
        return self._caches[sid]

    def clear(self, session_id: str) -> None:
        self._caches.pop(session_id.strip(), None)
