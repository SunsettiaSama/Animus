from __future__ import annotations

from ...io.inbound.persona import PersonaComposeRequest
from ...persona import SpeakPersonaLayer
from ..core.base import BlockContext, ComposeTarget
from ..core.types import BlockId, BlockSnapshot
from ..core.util import distilled_context


class PersonaBlock:
    block_id: BlockId = "persona"
    writes_to = frozenset({"persona.*"})

    def snapshot(self, ctx: BlockContext) -> BlockSnapshot:
        version = ctx.io.outbound.persona.version(ctx.session_id)
        persona_snap = ctx.io.outbound.persona.snapshot(ctx.session_id)
        summary = ""
        if isinstance(persona_snap, dict):
            summary = str(persona_snap.get("self_narrative") or "").strip()
        return BlockSnapshot(
            block="persona",
            summary=summary[:200],
            version=version,
        )

    def refresh(self, ctx: BlockContext, decision, target: ComposeTarget, *, plan) -> None:
        bundle = target.bundle
        if bundle is None:
            return
        sid = ctx.session_id
        io = ctx.io
        if not decision.refresh:
            if io.outbound.persona.service.active(sid) is not None:
                io.outbound.persona.apply_to_bundle(bundle, sid)
            target.frame.persona = bundle.persona
            if target.assembly is not None:
                version = io.outbound.persona.version(sid) or 0
                target.assembly.set_slot(
                    "persona",
                    narrative=bundle.persona.self_narrative.strip(),
                    version=version,
                )
            return
        text = distilled_context(bundle)
        io.inbound.persona.sync_for_compose(
            PersonaComposeRequest(
                session_id=sid,
                turn_index=ctx.turn_index,
                force=decision.refresh,
                injected_context=text,
                dialogue_compressed=text,
            ),
            force=decision.refresh,
        )
        io.outbound.persona.apply_to_bundle(bundle, sid)
        target.frame.persona = bundle.persona
        if target.assembly is not None:
            version = io.outbound.persona.version(sid) or 0
            target.assembly.set_slot(
                "persona",
                narrative=bundle.persona.self_narrative.strip(),
                version=version,
            )

    def apply(self, ctx: BlockContext, decision, bundle, *, plan) -> None:
        if not decision.include:
            bundle.persona = SpeakPersonaLayer()
            return
        frame = plan.prepared_frame
        if frame is None:
            return
        from ..core.base import ComposeTarget, PlanSidecar

        target = ComposeTarget(
            frame=frame,
            bundle=bundle,
            sidecar=PlanSidecar(),
        )
        self.refresh(ctx, decision, target, plan=plan)

    def kick(self, ctx: BlockContext, plan, ledger) -> list[str]:
        return []

    def post_turn(self, ctx: BlockContext, plan) -> list[str]:
        return []
