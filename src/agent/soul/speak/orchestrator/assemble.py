from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .guidance.interrupt import render_interrupt_system_block
from .guidance.social import apply_session_social, resolve_social_user_text
from .scene import apply_story_scene
from .turn_assembler import TurnComposeAssembler

if TYPE_CHECKING:
    from agent.soul.speak.io.outbound.stream import SpeakAgentOutput
    from agent.soul.speak.session.manage.coordinator import SessionSocialManager
    from agent.soul.speak.session.queue.types import InterruptContext

    from .bundle import SpeakPromptBundle, SpeakTurnMode
    from .compose_reconcile import ComposeReconcilePlan
    from .compose_slots import TurnComposeAssembly
    from .guidance.share.state import ShareComposeState
    from .io import OrchestratorIOHub
    from .session.port import SessionComposePort

APPEND_CONTINUE_INSTRUCTION = (
    "请继续完成本轮尚未说完的内容；输出仍需包含 [think]…[/think] 与 "
    "[state]finish[/state]（或 [state]append[/state]）。"
)

_turn_assembler = TurnComposeAssembler()


def finish_turn_bundle(
    bundle: SpeakPromptBundle,
    *,
    social: SessionSocialManager,
    session_id: str,
    user_text: str,
    turn_index: int,
    mode: SpeakTurnMode = "inbound",
    story_port: Any | None = None,
    world_id_fn: Callable[[], str] | None = None,
    io: OrchestratorIOHub | None = None,
    share_queue_count: int = 0,
    share_state: ShareComposeState | None = None,
    use_session_share_queue: bool = False,
    pop_presence_share_at: Callable[[str, int], bool] | None = None,
    pop_session_share_at: Callable[[str, int], bool] | None = None,
    mark_recall_unit_consumed: Callable[[str, str], None] | None = None,
    session_port: SessionComposePort | None = None,
    reconcile_plan: ComposeReconcilePlan | None = None,
) -> SpeakPromptBundle:
    _turn_assembler.assemble_turn(
        bundle,
        session_id=session_id,
        turn_index=turn_index,
        user_text=user_text,
        io=io,
        share_queue_count=share_queue_count,
        share_state=share_state,
        use_session_share_queue=use_session_share_queue,
        pop_presence_share_at=pop_presence_share_at,
        pop_session_share_at=pop_session_share_at,
        mark_recall_unit_consumed=mark_recall_unit_consumed,
        session_port=session_port,
        reconcile_plan=reconcile_plan,
    )
    apply_session_social(
        bundle,
        social,
        session_id=session_id,
        turn_index=turn_index,
        user_text=user_text,
        mode=mode,
    )
    apply_story_scene(
        bundle,
        story_port=story_port,
        world_id_fn=world_id_fn,
        user_text=user_text,
    )
    return bundle


def build_turn_system(
    bundle: SpeakPromptBundle,
    *,
    interrupt_context: InterruptContext | None = None,
    round_idx: int = 0,
    partial_output: str = "",
    parsed: SpeakAgentOutput | None = None,
) -> str:
    system = bundle.build_system()
    if interrupt_context is not None:
        system = f"{system}\n\n{render_interrupt_system_block(interrupt_context)}"
    if round_idx > 0 and parsed is not None and parsed.session_state == "append":
        system = f"{system}\n\n{APPEND_CONTINUE_INSTRUCTION}"
        if partial_output.strip():
            system = f"{system}\n\n【已输出片段】\n{partial_output.strip()}"
    brew_hint = bundle.meta.get("recent_brew_lines")
    if isinstance(brew_hint, str) and brew_hint.strip():
        system = f"{system}\n\n【勿重复】{brew_hint.strip()}"
    return system


def resolve_llm_user_text(
    bundle: SpeakPromptBundle,
    user_text: str,
    *,
    round_idx: int = 0,
    parsed: SpeakAgentOutput | None = None,
) -> str:
    if round_idx > 0 and parsed is not None and parsed.session_state == "append":
        return "请接着说完，不要重复已输出内容。"
    return resolve_social_user_text(bundle, user_text)
