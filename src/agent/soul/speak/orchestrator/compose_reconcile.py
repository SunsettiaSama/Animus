from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .compose_slots import KNOWN_COMPOSE_BLOCKS, ComposeBlockId

if TYPE_CHECKING:
    from .io import OrchestratorIOHub
    from .session.port import SessionComposeSignals

ComposeDirectiveAction = Literal["refresh", "apply_only"]


@dataclass(frozen=True)
class ComposeVersionLedger:
    persona: int | None = None
    scene: int | None = None
    guidance: int | None = None
    turn_index: int | None = None
    generation: int | None = None

    def get(self, block: ComposeBlockId) -> int | None:
        return getattr(self, block)

    def snapshot(self) -> dict[str, object]:
        return {
            "persona": self.persona,
            "scene": self.scene,
            "guidance": self.guidance,
            "turn_index": self.turn_index,
            "generation": self.generation,
        }


@dataclass(frozen=True)
class ComposeBlockDirective:
    block: ComposeBlockId
    action: ComposeDirectiveAction
    force: bool = False
    reason: str = ""

    def snapshot(self) -> dict[str, object]:
        return {
            "block": self.block,
            "action": self.action,
            "force": self.force,
            "reason": self.reason,
        }


@dataclass
class ComposeReconcilePlan:
    session: SessionComposeSignals
    bundle_ledger: ComposeVersionLedger
    live_ledger: ComposeVersionLedger
    directives: tuple[ComposeBlockDirective, ...] = ()
    notes: list[str] = field(default_factory=list)

    def directive_for(self, block: ComposeBlockId) -> ComposeBlockDirective:
        for item in self.directives:
            if item.block == block:
                return item
        return ComposeBlockDirective(block=block, action="refresh", force=True, reason="missing_directive")

    def snapshot(self) -> dict[str, Any]:
        return {
            "session": self.session.snapshot(),
            "bundle_ledger": self.bundle_ledger.snapshot(),
            "live_ledger": self.live_ledger.snapshot(),
            "directives": [d.snapshot() for d in self.directives],
            "notes": list(self.notes),
        }


def _meta_int(meta: dict[str, Any], key: str) -> int | None:
    raw = meta.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    return int(raw)


def read_bundle_ledger(meta: dict[str, Any]) -> ComposeVersionLedger:
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
                if block in KNOWN_COMPOSE_BLOCKS and isinstance(version, int):
                    versions[str(block)] = version
            if versions:
                return ComposeVersionLedger(
                    persona=versions.get("persona"),
                    scene=versions.get("scene"),
                    guidance=versions.get("guidance"),
                    turn_index=_meta_int(meta, "compose_session_turn"),
                    generation=_meta_int(meta, "compose_session_generation"),
                )
    return ComposeVersionLedger(
        persona=_meta_int(meta, "persona_compose_version"),
        scene=_meta_int(meta, "scene_compose_version"),
        guidance=_meta_int(meta, "guidance_compose_version"),
        turn_index=_meta_int(meta, "compose_session_turn"),
        generation=_meta_int(meta, "compose_session_generation"),
    )


def read_live_ledger(io: OrchestratorIOHub, session_id: str) -> ComposeVersionLedger:
    return ComposeVersionLedger(
        persona=io.outbound.persona.version(session_id),
        scene=io.outbound.scene.version(session_id),
        guidance=io.outbound.guidance.version(session_id),
    )


def write_session_ledger(meta: dict[str, Any], session: SessionComposeSignals) -> None:
    meta["compose_session_turn"] = session.turn_index
    meta["compose_session_generation"] = session.generation
    meta["compose_session_interactor"] = session.interactor_id


class ComposeReconcileAgent:
    """编排判定：对比 bundle 已登记版本与域内 live 版本，生成子模块更新指令。"""

    def plan(
        self,
        *,
        bundle_meta: dict[str, Any],
        io: OrchestratorIOHub,
        session: SessionComposeSignals,
    ) -> ComposeReconcilePlan:
        bundle_ledger = read_bundle_ledger(bundle_meta)
        live_ledger = read_live_ledger(io, session.session_id)
        notes: list[str] = []
        directives: list[ComposeBlockDirective] = []

        session_stale = (
            bundle_ledger.turn_index is not None
            and bundle_ledger.turn_index != session.turn_index
        )
        generation_stale = (
            bundle_ledger.generation is not None
            and bundle_ledger.generation != session.generation
        )
        if session_stale:
            notes.append(
                f"compose_reconcile: session turn {bundle_ledger.turn_index}"
                f" -> {session.turn_index}"
            )
        if generation_stale:
            notes.append(
                f"compose_reconcile: session generation {bundle_ledger.generation}"
                f" -> {session.generation}"
            )

        for block in KNOWN_COMPOSE_BLOCKS:
            applied = bundle_ledger.get(block)
            live = live_ledger.get(block)
            directive = self._directive_for_block(
                block,
                applied=applied,
                live=live,
                session_stale=session_stale or generation_stale,
            )
            if directive.action == "refresh":
                notes.append(
                    f"compose_reconcile: {block} {directive.reason}"
                    f" (bundle={applied}, live={live})"
                )
            directives.append(directive)

        return ComposeReconcilePlan(
            session=session,
            bundle_ledger=bundle_ledger,
            live_ledger=live_ledger,
            directives=tuple(directives),
            notes=notes,
        )

    def _directive_for_block(
        self,
        block: ComposeBlockId,
        *,
        applied: int | None,
        live: int | None,
        session_stale: bool,
    ) -> ComposeBlockDirective:
        if session_stale:
            return ComposeBlockDirective(
                block=block,
                action="refresh",
                force=True,
                reason="session_turn_or_generation_changed",
            )
        if applied is None and live is None:
            return ComposeBlockDirective(
                block=block,
                action="refresh",
                force=False,
                reason="initial_compose",
            )
        if applied is None and live is not None:
            return ComposeBlockDirective(
                block=block,
                action="apply_only",
                force=False,
                reason="bundle_missing_version",
            )
        if applied is not None and live is None:
            return ComposeBlockDirective(
                block=block,
                action="refresh",
                force=True,
                reason="live_missing",
            )
        if applied != live:
            return ComposeBlockDirective(
                block=block,
                action="refresh",
                force=True,
                reason="version_mismatch",
            )
        return ComposeBlockDirective(
            block=block,
            action="apply_only",
            force=False,
            reason="version_aligned",
        )


def build_compose_reconcile_plan(
    *,
    bundle_meta: dict[str, Any],
    io: OrchestratorIOHub,
    session: SessionComposeSignals,
) -> ComposeReconcilePlan:
    return ComposeReconcileAgent().plan(
        bundle_meta=bundle_meta,
        io=io,
        session=session,
    )
