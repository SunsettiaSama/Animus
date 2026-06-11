from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..blocks.core.base import ComposeTarget, PlanSidecar
from ..blocks.core.ledger import write_session_ledger
from ..blocks.core.types import TurnBlockAssembly
from ..blocks.registry import BlockRegistry
from ..bundle import SpeakPromptBundle
from ..director.decide import decide_plan
from ..frame import PreparedComposeFrame
from ..guidance.layer import SpeakGuidanceLayer
from ..persona import SpeakPersonaLayer
from ..scene import SpeakSceneLayer
from ..system.build import build_system_layer
from ..system.reply_style import SpeakReplyStyle
from .context import ComposePipelineContext

if TYPE_CHECKING:
    from ..director.types import DirectorPlan
    from ..orchestrator import SpeakOrchestrator


class ComposePipeline:
    def __init__(
        self,
        orchestrator: SpeakOrchestrator,
        *,
        registry: BlockRegistry | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._registry = registry or BlockRegistry()

    @property
    def registry(self) -> BlockRegistry:
        return self._registry

    def produce_plan(
        self,
        ctx: ComposePipelineContext,
        *,
        target_turn_index: int,
        bundle_meta: dict[str, Any] | None = None,
        cold_start: bool = False,
        social_armed: str | None = None,
        silence_armed: bool = False,
        share_wants: bool = False,
        agent_text: str = "",
    ) -> DirectorPlan:
        ctx.turn_index = target_turn_index
        plan = decide_plan(
            self._orchestrator,
            session_id=ctx.session_id,
            target_turn_index=target_turn_index,
            user_text=ctx.user_text,
            generation=ctx.generation,
            bundle_meta=bundle_meta,
            cold_start=cold_start,
            social_armed=social_armed,  # type: ignore[arg-type]
            silence_armed=silence_armed,
            share_wants=share_wants,
        )
        if agent_text.strip():
            plan.notes.append(f"director_produce: agent_text_len={len(agent_text.strip())}")
        return self.refresh(plan, ctx)

    def refresh(
        self,
        plan: DirectorPlan,
        ctx: ComposePipelineContext,
    ) -> DirectorPlan:
        block_ctx = ctx.to_block_context()
        block_ctx.turn_index = plan.target_turn_index
        style = ctx.reply_style or SpeakReplyStyle()
        frame = PreparedComposeFrame(
            session_id=plan.session_id,
            mode=ctx.mode,
            generation=plan.generation,
            system=build_system_layer(
                mode=ctx.mode,
                output_format=style.render_prompt(),
            ),
            persona=SpeakPersonaLayer(),
            scene=SpeakSceneLayer(),
            guidance=SpeakGuidanceLayer(),
            reply_style=style,
        )
        bundle = SpeakPromptBundle(
            session_id=plan.session_id,
            mode=ctx.mode,
            system=frame.system,
            persona=frame.persona,
            scene=frame.scene,
            guidance=SpeakGuidanceLayer(
                share_preview=frame.guidance.share_preview,
                control_arc=frame.guidance.control_arc,
            ),
            user_text=ctx.user_text.strip(),
            wants_share=frame.wants_share,
            share_summary=frame.share_summary,
            reply_style=style,
        )
        assembly = TurnBlockAssembly(
            session_id=plan.session_id,
            turn_index=plan.target_turn_index,
        )
        target = ComposeTarget(
            frame=frame,
            sidecar=PlanSidecar(),
            bundle=bundle,
            assembly=assembly,
        )
        self._registry.refresh(plan, target, block_ctx)
        frame.persona = bundle.persona
        frame.scene = bundle.scene
        frame.guidance = SpeakGuidanceLayer(
            share_preview=bundle.guidance.share_preview if plan.share.include_preview else "",
            control_arc=bundle.guidance.control_arc,
            recall_preview=bundle.guidance.recall_preview,
            interactor_portrait=bundle.guidance.interactor_portrait,
            social_blocks=list(bundle.guidance.social_blocks),
        )
        frame.wants_share = block_ctx.share_state.wants_share if block_ctx.share_state else False
        frame.share_summary = block_ctx.share_state.summary if block_ctx.share_state else ""
        frame.notes.extend(plan.notes)
        plan.prepared_frame = frame
        plan.control_snapshot = target.sidecar.control_snapshot or plan.control_snapshot
        assembly.attach_meta(bundle.meta)
        return plan

    def kick_memory(
        self,
        plan: DirectorPlan,
        ctx: ComposePipelineContext,
        ledger,
    ) -> list[str]:
        block_ctx = ctx.to_block_context()
        block_ctx.turn_index = plan.target_turn_index
        return self._registry.kick(plan, block_ctx, ledger)

    def apply(
        self,
        plan: DirectorPlan,
        bundle: SpeakPromptBundle,
        ctx: ComposePipelineContext,
    ) -> SpeakPromptBundle:
        block_ctx = ctx.to_block_context()
        block_ctx.turn_index = plan.target_turn_index
        self._registry.apply(plan, bundle, block_ctx, include_social=False)
        return bundle

    def finish_turn(
        self,
        plan: DirectorPlan,
        bundle: SpeakPromptBundle,
        ctx: ComposePipelineContext,
    ) -> SpeakPromptBundle:
        block_ctx = ctx.to_block_context()
        block_ctx.turn_index = plan.target_turn_index
        self._registry.apply(plan, bundle, block_ctx, include_social=True)
        bundle.notes.append(
            f"compose_director: applied plan turn={plan.target_turn_index}",
        )
        bundle.meta["compose_director_plan"] = plan.snapshot()
        if self._orchestrator._session_port is not None:
            session = self._orchestrator._session_port.signals(plan.session_id)
            write_session_ledger(bundle.meta, session)
        io = block_ctx.io
        sid = plan.session_id
        assembly = TurnBlockAssembly(
            session_id=sid,
            turn_index=plan.target_turn_index,
        )
        assembly.set_slot(
            "persona",
            narrative=bundle.persona.self_narrative.strip(),
            version=io.outbound.persona.version(sid) or 0,
        )
        assembly.set_slot(
            "scene",
            narrative=bundle.scene.world_scene.strip(),
            version=io.outbound.scene.version(sid) or 0,
        )
        control = plan.control_snapshot or io.inbound.guidance.control.active(sid)
        guidance_narrative = control.narrative.strip() if control is not None else bundle.guidance.control_arc.strip()
        assembly.set_slot(
            "guidance",
            narrative=guidance_narrative,
            version=io.outbound.guidance.version(sid) or 0,
        )
        assembly.attach_meta(bundle.meta)
        bundle.notes.append(
            "compose_assembly: "
            + ", ".join(
                f"{s.block}=v{s.version}" for s in assembly.slots_in_order()
            ),
        )
        self._orchestrator.touch_compose_cache_from_meta(plan.session_id, bundle.meta)
        return bundle

    def post_turn(
        self,
        plan: DirectorPlan,
        ctx: ComposePipelineContext,
    ) -> list[str]:
        block_ctx = ctx.to_block_context()
        block_ctx.turn_index = plan.target_turn_index
        notes = self._registry.post_turn(plan, block_ctx)
        return notes

    def sync_stale(
        self,
        session_id: str,
        *,
        generation: int,
        turn_index: int,
        user_text: str = "",
    ) -> list[str]:
        from ..blocks.core.ledger import stale_map

        sid = session_id.strip()
        port = self._orchestrator._session_port
        if port is None:
            return ["session_compose_sync: no session port"]
        cache = self._orchestrator.compose_cache(sid)
        session = port.signals(sid)
        stale = stale_map(cache.meta_snapshot(), self._orchestrator.io, session)
        notes: list[str] = [f"session_compose_sync: start {sid}"]
        ctx = ComposePipelineContext(
            orchestrator=self._orchestrator,
            session_id=sid,
            turn_index=turn_index,
            user_text=user_text,
            generation=generation,
        )
        block_ctx = ctx.to_block_context()
        plan = decide_plan(
            self._orchestrator,
            session_id=sid,
            target_turn_index=turn_index,
            user_text=user_text,
            generation=generation,
            bundle_meta=cache.meta_snapshot(),
            cold_start=False,
        )
        frame = PreparedComposeFrame(
            session_id=sid,
            mode=ctx.mode,
            generation=generation,
            system=build_system_layer(mode=ctx.mode),
            persona=SpeakPersonaLayer(),
            scene=SpeakSceneLayer(),
            guidance=SpeakGuidanceLayer(),
        )
        bundle = SpeakPromptBundle(session_id=sid, mode=ctx.mode)
        target = ComposeTarget(frame=frame, bundle=bundle)
        self._registry.sync_stale_refresh(plan, target, block_ctx, stale)
        meta = cache.meta_snapshot()
        meta.update(bundle.meta)
        cache.update_from_meta(meta)
        notes.append("session_compose_sync: done")
        return notes
