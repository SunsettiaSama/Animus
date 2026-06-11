from __future__ import annotations

from ...io.inbound.scene import SceneUpdateRequest
from ...scene import apply_story_scene
from ..core.base import BlockContext, ComposeTarget
from ..core.types import BlockId, BlockSnapshot


class SceneBlock:
    block_id: BlockId = "scene"
    writes_to = frozenset({"scene.*"})

    def snapshot(self, ctx: BlockContext) -> BlockSnapshot:
        version = ctx.io.outbound.scene.version(ctx.session_id)
        scene_snap = ctx.io.outbound.scene.snapshot(ctx.session_id)
        text = ""
        if isinstance(scene_snap, dict):
            text = str(scene_snap.get("world_scene") or "").strip()
        return BlockSnapshot(
            block="scene",
            summary=text[:200],
            version=version,
        )

    def refresh(self, ctx: BlockContext, decision, target: ComposeTarget, *, plan) -> None:
        bundle = target.bundle
        if bundle is None:
            return
        sid = ctx.session_id
        io = ctx.io
        query = ctx.user_text.strip()
        if not query:
            if not decision.refresh:
                io.outbound.scene.apply_to_bundle(bundle, sid)
            target.frame.scene = bundle.scene
            if target.assembly is not None:
                version = io.outbound.scene.version(sid) or 0
                target.assembly.set_slot(
                    "scene",
                    narrative=bundle.scene.world_scene.strip(),
                    version=version,
                )
            return
        if not decision.refresh:
            io.outbound.scene.apply_to_bundle(bundle, sid)
            target.frame.scene = bundle.scene
            if target.assembly is not None:
                version = io.outbound.scene.version(sid) or 0
                target.assembly.set_slot(
                    "scene",
                    narrative=bundle.scene.world_scene.strip(),
                    version=version,
                )
            return
        io.inbound.scene.sync_for_turn(
            SceneUpdateRequest(
                session_id=sid,
                turn_index=ctx.turn_index,
                query=query,
                force=decision.refresh,
            ),
            force=decision.refresh,
        )
        io.outbound.scene.apply_to_bundle(bundle, sid)
        target.frame.scene = bundle.scene
        if target.assembly is not None:
            version = io.outbound.scene.version(sid) or 0
            target.assembly.set_slot(
                "scene",
                narrative=bundle.scene.world_scene.strip(),
                version=version,
            )

    def apply(self, ctx: BlockContext, decision, bundle, *, plan) -> None:
        if not decision.include:
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
        apply_story_scene(
            bundle,
            story_port=ctx.story_port,
            world_id_fn=ctx.world_id_fn,
            user_text=ctx.user_text,
        )

    def kick(self, ctx: BlockContext, plan, ledger) -> list[str]:
        return []

    def post_turn(self, ctx: BlockContext, plan) -> list[str]:
        return []
