from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ...frame import PreparedComposeFrame
from ...system.reply_style import SpeakReplyStyle
from ...system.role import SpeakTurnMode
from .types import BlockId, BlockSnapshot, PlanSidecar, TurnBlockAssembly

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent.soul.speak.session.manage.coordinator import SessionSocialManager

    from ...bundle import SpeakPromptBundle
    from ...director.types import DirectorPlan, ModuleDecision
    from ...guidance.share.state import ShareComposeState
    from ...io import OrchestratorIOHub
    from ...orchestrator import SpeakOrchestrator
    from ...session.port import SessionComposePort
    from ....io.inbound.memory.compose_bridge import InboundMemoryComposeBridge


@dataclass
class BlockContext:
    orchestrator: SpeakOrchestrator
    io: OrchestratorIOHub
    session_id: str
    turn_index: int
    user_text: str
    mode: SpeakTurnMode
    generation: int
    reply_style: SpeakReplyStyle
    share_state: ShareComposeState | None = None
    share_queue_count: int = 0
    use_session_share_queue: bool = False
    social: SessionSocialManager | None = None
    story_port: Any | None = None
    world_id_fn: Callable[[], str] | None = None
    memory_compose: InboundMemoryComposeBridge | None = None
    similar: Any = None
    portrait: Any = None
    session_port: SessionComposePort | None = None
    pop_presence_share_at: Callable[[str, int], bool] | None = None
    pop_session_share_at: Callable[[str, int], bool] | None = None
    mark_recall_unit_consumed: Callable[[str, str], None] | None = None
    applied: bool = False


@dataclass
class ComposeTarget:
    frame: PreparedComposeFrame
    sidecar: PlanSidecar = field(default_factory=PlanSidecar)
    bundle: SpeakPromptBundle | None = None
    assembly: TurnBlockAssembly | None = None


class PromptBlock(Protocol):
    block_id: BlockId
    writes_to: frozenset[str]

    def snapshot(self, ctx: BlockContext) -> BlockSnapshot: ...

    def refresh(
        self,
        ctx: BlockContext,
        decision: ModuleDecision,
        target: ComposeTarget,
        *,
        plan: DirectorPlan,
    ) -> None: ...

    def apply(
        self,
        ctx: BlockContext,
        decision: ModuleDecision,
        bundle: SpeakPromptBundle,
        *,
        plan: DirectorPlan,
    ) -> None: ...

    def kick(
        self,
        ctx: BlockContext,
        plan: DirectorPlan,
        ledger: Any,
    ) -> list[str]: ...

    def post_turn(
        self,
        ctx: BlockContext,
        plan: DirectorPlan,
    ) -> list[str]: ...
