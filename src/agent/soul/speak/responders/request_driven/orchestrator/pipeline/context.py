from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..blocks.system.reply_style import SpeakReplyStyle
from ..blocks.system.role import SpeakTurnMode
from ..blocks.core.base import BlockContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent.soul.speak.session.manage.coordinator import SessionSocialManager

    from ..orchestrator import SpeakOrchestrator
    from agent.soul.speak.io.inbound.memory.compose_bridge import InboundMemoryComposeBridge


@dataclass
class ComposePipelineContext:
    orchestrator: SpeakOrchestrator
    session_id: str
    turn_index: int = 0
    user_text: str = ""
    mode: SpeakTurnMode = "inbound"
    generation: int = 0
    reply_style: SpeakReplyStyle = field(default_factory=SpeakReplyStyle)
    social: SessionSocialManager | None = None
    story_port: Any | None = None
    world_id_fn: Callable[[], str] | None = None
    memory_compose: InboundMemoryComposeBridge | None = None
    similar: Any = None
    portrait: Any = None
    pop_presence_share_at: Callable[[str, int], bool] | None = None
    pop_session_share_at: Callable[[str, int], bool] | None = None
    mark_recall_unit_consumed: Callable[[str, str], None] | None = None

    def to_block_context(self) -> BlockContext:
        orch = self.orchestrator
        presence_snap = orch._presence.snapshot(self.session_id)
        share_state = orch._share.collect(presence_snap, session_id=self.session_id)
        share_count = share_state.count
        return BlockContext(
            orchestrator=orch,
            io=orch.io,
            session_id=self.session_id.strip(),
            turn_index=self.turn_index,
            user_text=self.user_text,
            mode=self.mode,
            generation=self.generation,
            reply_style=self.reply_style,
            share_state=share_state,
            share_queue_count=share_count,
            use_session_share_queue=orch.uses_session_share_queue(self.session_id),
            social=self.social,
            story_port=self.story_port,
            world_id_fn=self.world_id_fn,
            memory_compose=self.memory_compose,
            similar=self.similar,
            portrait=self.portrait,
            session_port=orch._session_port,
            pop_presence_share_at=self.pop_presence_share_at,
            pop_session_share_at=self.pop_session_share_at,
            mark_recall_unit_consumed=self.mark_recall_unit_consumed,
        )
