from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .context import ContextBlock
from .core.base import BlockContext, ComposeTarget, PromptBlock
from .core.types import REFRESH_ORDER, BlockId, BlockSnapshot, TurnBlockAssembly
from .guidance.block import GuidanceBlock
from .memory.block import MemoryBlock
from .persona.block import PersonaBlock
from .scene.block import SceneBlock
from .share.block import ShareBlock
from .social.block import SocialBlock
from .system.block import SystemBlock

if TYPE_CHECKING:
    from ..bundle import SpeakPromptBundle
    from ..director.types import DirectorPlan


class BlockRegistry:
    """Prompt 块注册表：唯一块适配调度入口。"""

    def __init__(self) -> None:
        self._blocks: dict[BlockId, PromptBlock] = {
            "system": SystemBlock(),
            "persona": PersonaBlock(),
            "scene": SceneBlock(),
            "guidance": GuidanceBlock(),
            "context": ContextBlock(),
            "memory": MemoryBlock(),
            "social": SocialBlock(),
            "share": ShareBlock(),
        }

    def get(self, block_id: BlockId) -> PromptBlock:
        return self._blocks[block_id]

    def collect_snapshots(self, ctx: BlockContext) -> tuple[BlockSnapshot, ...]:
        snapshots: list[BlockSnapshot] = []
        for block_id in self._blocks:
            snapshots.append(self._blocks[block_id].snapshot(ctx))
        return tuple(snapshots)

    def refresh(
        self,
        plan: DirectorPlan,
        target: ComposeTarget,
        ctx: BlockContext,
    ) -> None:
        from ..director.types import ModuleDecision

        system_dec = ModuleDecision(
            block="system",  # type: ignore[arg-type]
            refresh=True,
            include=True,
            reason="produce",
        )
        self._blocks["system"].refresh(ctx, system_dec, target, plan=plan)
        for block_id in REFRESH_ORDER:
            if block_id == "system":
                continue
            decision = plan.decision_for(block_id)  # type: ignore[arg-type]
            if decision is None:
                continue
            self._blocks[block_id].refresh(ctx, decision, target, plan=plan)

    def apply(
        self,
        plan: DirectorPlan,
        bundle: SpeakPromptBundle,
        ctx: BlockContext,
        *,
        include_social: bool = False,
    ) -> None:
        for block_id, block in self._blocks.items():
            if block_id == "social" and not include_social:
                continue
            decision = plan.decision_for(block_id)  # type: ignore[arg-type]
            if decision is None:
                continue
            block.apply(ctx, decision, bundle, plan=plan)

    def kick(
        self,
        plan: DirectorPlan,
        ctx: BlockContext,
        ledger: Any,
    ) -> list[str]:
        return self._blocks["memory"].kick(ctx, plan, ledger)

    def post_turn(
        self,
        plan: DirectorPlan,
        ctx: BlockContext,
    ) -> list[str]:
        notes: list[str] = []
        notes.extend(self._blocks["guidance"].post_turn(ctx, plan))
        return notes

    def sync_stale_refresh(
        self,
        plan: DirectorPlan,
        target: ComposeTarget,
        ctx: BlockContext,
        stale: dict[BlockId, bool],
    ) -> None:
        for block_id in ("persona", "scene", "guidance"):
            if not stale.get(block_id, False):
                continue
            decision = plan.decision_for(block_id)  # type: ignore[arg-type]
            if decision is None:
                continue
            forced = decision.__class__(
                block=decision.block,
                refresh=True,
                include=decision.include,
                reason=f"sync_stale:{decision.reason}",
                guidance_trigger=decision.guidance_trigger,
            )
            self._blocks[block_id].refresh(ctx, forced, target, plan=plan)

    def build_assembly(
        self,
        ctx: BlockContext,
        *,
        turn_index: int,
    ) -> TurnBlockAssembly:
        assembly = TurnBlockAssembly(session_id=ctx.session_id, turn_index=turn_index)
        for block_id in ("persona", "scene", "guidance"):
            version = ctx.io.outbound.__getattribute__(block_id).version(ctx.session_id) or 0
            snap = ctx.io.outbound.__getattribute__(block_id).snapshot(ctx.session_id)
            narrative = ""
            if block_id == "persona" and isinstance(snap, dict):
                narrative = str(snap.get("self_narrative") or "").strip()
            elif block_id == "scene" and isinstance(snap, dict):
                narrative = str(snap.get("world_scene") or "").strip()
            elif block_id == "guidance":
                control = ctx.io.inbound.guidance.control.active(ctx.session_id)
                if control is not None:
                    narrative = control.narrative.strip()
            assembly.set_slot(block_id, narrative=narrative, version=version)
        return assembly
