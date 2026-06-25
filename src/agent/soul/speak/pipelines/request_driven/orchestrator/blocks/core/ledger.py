from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .types import VERSIONED_BLOCKS, BlockId, BlockVersionLedger

if TYPE_CHECKING:
    from ...io import OrchestratorIOHub
    from ...session.port import SessionComposeSignals


def _meta_int(meta: dict[str, Any], key: str) -> int | None:
    raw = meta.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    return int(raw)


def read_bundle_ledger(meta: dict[str, Any]) -> BlockVersionLedger:
    assembly = meta.get("turn_compose_assembly")
    if isinstance(assembly, dict):
        slots = assembly.get("slots")
        if isinstance(slots, list):
            versions: dict[str, int | None] = {}
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                block = slot.get("block")
                version = slot.get("version")
                if block in VERSIONED_BLOCKS and isinstance(version, int):
                    versions[str(block)] = version
            if versions:
                return BlockVersionLedger(
                    persona=versions.get("persona"),
                    scene=versions.get("scene"),
                    guidance=versions.get("guidance"),
                    turn_index=_meta_int(meta, "compose_session_turn"),
                    generation=_meta_int(meta, "compose_session_generation"),
                )
    return BlockVersionLedger(
        persona=_meta_int(meta, "persona_compose_version"),
        scene=_meta_int(meta, "scene_compose_version"),
        guidance=_meta_int(meta, "guidance_compose_version"),
        turn_index=_meta_int(meta, "compose_session_turn"),
        generation=_meta_int(meta, "compose_session_generation"),
    )


def read_live_ledger(io: OrchestratorIOHub, session_id: str) -> BlockVersionLedger:
    return BlockVersionLedger(
        persona=io.outbound.persona.version(session_id),
        scene=io.outbound.scene.version(session_id),
        guidance=io.outbound.guidance.version(session_id),
    )


def write_session_ledger(meta: dict[str, Any], session: SessionComposeSignals) -> None:
    meta["compose_session_turn"] = session.turn_index
    meta["compose_session_generation"] = session.generation
    meta["compose_session_interactor"] = session.interactor_id


def _block_stale(
    block: BlockId,
    *,
    applied: int | None,
    live: int | None,
    session_stale: bool,
) -> bool:
    if session_stale:
        return True
    if applied is None and live is None:
        return True
    if applied is None and live is not None:
        return False
    if applied is not None and live is None:
        return True
    if applied != live:
        return True
    return False


def stale_map(
    bundle_meta: dict[str, Any],
    io: OrchestratorIOHub,
    session: SessionComposeSignals,
) -> dict[BlockId, bool]:
    bundle_ledger = read_bundle_ledger(bundle_meta)
    live_ledger = read_live_ledger(io, session.session_id)
    session_stale = (
        bundle_ledger.turn_index is not None
        and bundle_ledger.turn_index != session.turn_index
    ) or (
        bundle_ledger.generation is not None
        and bundle_ledger.generation != session.generation
    )
    out: dict[BlockId, bool] = {}
    for block in VERSIONED_BLOCKS:
        out[block] = _block_stale(
            block,
            applied=bundle_ledger.get(block),
            live=live_ledger.get(block),
            session_stale=session_stale,
        )
    return out
