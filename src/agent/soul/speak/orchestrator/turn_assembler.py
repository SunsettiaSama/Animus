from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .compose_reconcile import ComposeReconcilePlan, build_compose_reconcile_plan, write_session_ledger
from .compose_slots import TurnComposeAssembly
from .guidance.control.consume import consume_guidance_emits
from .guidance.control.candidate_types import RecallPlannerCandidate
from .guidance.inbound.persona_brief import (
    build_guidance_plan_request,
    stash_persona_outbound_brief,
)
from .persona.outbound.brief import collect_persona_outbound_brief
from .guidance.share.candidates import format_share_candidates, select_share_candidates

if TYPE_CHECKING:
    from agent.soul.speak.session.manage.coordinator import SessionSocialManager

    from .bundle import SpeakPromptBundle, SpeakTurnMode
    from .guidance.share.state import ShareComposeState
    from .io import OrchestratorIOHub
    from .session.port import SessionComposePort


def _recall_candidates_from_bundle(
    bundle: SpeakPromptBundle,
) -> tuple[RecallPlannerCandidate, ...]:
    raw = bundle.meta.get("guidance_recall_candidates")
    if not raw:
        return ()
    if isinstance(raw, tuple):
        return raw
    return tuple(raw)


def _distilled_context(bundle: SpeakPromptBundle) -> str:
    distilled = bundle.persona.dialogue_compressed.strip()
    if not distilled:
        distilled = bundle.guidance.context_distill.strip()
    if not distilled:
        return ""
    lines = [line.strip() for line in distilled.splitlines() if line.strip()]
    body: list[str] = []
    for line in lines:
        if line.startswith("【") and "】" in line:
            continue
        if line.startswith("以下为") or line.startswith("generation="):
            continue
        body.append(line.lstrip("- ").strip())
    return "\n".join(body) if body else distilled[:400]


class TurnComposeAssembler:
    """Orchestrator 顶层编排：persona → scene → guidance，登记叙述块与版本。"""

    def assemble_turn(
        self,
        bundle: SpeakPromptBundle,
        *,
        session_id: str,
        turn_index: int,
        user_text: str,
        io: OrchestratorIOHub | None,
        share_queue_count: int = 0,
        share_state: ShareComposeState | None = None,
        use_session_share_queue: bool = False,
        pop_presence_share_at: Callable[[str, int], bool] | None = None,
        pop_session_share_at: Callable[[str, int], bool] | None = None,
        mark_recall_unit_consumed: Callable[[str, str], None] | None = None,
        session_port: SessionComposePort | None = None,
        reconcile_plan: ComposeReconcilePlan | None = None,
    ) -> TurnComposeAssembly:
        assembly = TurnComposeAssembly(session_id=session_id, turn_index=turn_index)
        if io is None:
            assembly.attach_meta(bundle.meta)
            return assembly

        plan = reconcile_plan
        if plan is None and session_port is not None:
            session_signals = session_port.signals(session_id)
            plan = build_compose_reconcile_plan(
                bundle_meta=bundle.meta,
                io=io,
                session=session_signals,
            )
        if plan is not None:
            bundle.meta["compose_reconcile"] = plan.snapshot()
            bundle.notes.extend(plan.notes)
            write_session_ledger(bundle.meta, plan.session)

        self._run_persona(
            bundle,
            assembly=assembly,
            session_id=session_id,
            turn_index=turn_index,
            io=io,
            plan=plan,
        )
        self._run_scene(
            bundle,
            assembly=assembly,
            session_id=session_id,
            turn_index=turn_index,
            user_text=user_text,
            io=io,
            plan=plan,
        )
        self._run_guidance(
            bundle,
            assembly=assembly,
            session_id=session_id,
            turn_index=turn_index,
            io=io,
            share_queue_count=share_queue_count,
            share_state=share_state,
            use_session_share_queue=use_session_share_queue,
            pop_presence_share_at=pop_presence_share_at,
            pop_session_share_at=pop_session_share_at,
            mark_recall_unit_consumed=mark_recall_unit_consumed,
            plan=plan,
        )
        assembly.attach_meta(bundle.meta)
        bundle.notes.append(
            "compose_assembly: "
            + ", ".join(
                f"{s.block}=v{s.version}" for s in assembly.slots_in_order()
            )
        )
        return assembly

    def _run_persona(
        self,
        bundle: SpeakPromptBundle,
        *,
        assembly: TurnComposeAssembly,
        session_id: str,
        turn_index: int,
        io: OrchestratorIOHub,
        plan: ComposeReconcilePlan | None,
    ) -> None:
        from .io.inbound.persona import PersonaComposeRequest

        directive = plan.directive_for("persona") if plan is not None else None
        if directive is not None and directive.action == "apply_only":
            io.outbound.persona.apply_to_bundle(bundle, session_id)
            version = io.outbound.persona.version(session_id) or 0
            narrative = bundle.persona.self_narrative.strip()
            assembly.set_slot("persona", narrative=narrative, version=version)
            return

        distilled = _distilled_context(bundle)
        force = directive.force if directive is not None else False
        io.inbound.persona.sync_for_compose(
            PersonaComposeRequest(
                session_id=session_id,
                turn_index=turn_index,
                force=force,
                injected_context=distilled,
                dialogue_compressed=distilled,
            ),
            force=force,
        )
        io.outbound.persona.apply_to_bundle(bundle, session_id)
        version = io.outbound.persona.version(session_id) or 0
        narrative = bundle.persona.self_narrative.strip()
        assembly.set_slot("persona", narrative=narrative, version=version)

    def _run_scene(
        self,
        bundle: SpeakPromptBundle,
        *,
        assembly: TurnComposeAssembly,
        session_id: str,
        turn_index: int,
        user_text: str,
        io: OrchestratorIOHub,
        plan: ComposeReconcilePlan | None,
    ) -> None:
        directive = plan.directive_for("scene") if plan is not None else None
        query = user_text.strip()
        if not query:
            if directive is not None and directive.action == "apply_only":
                io.outbound.scene.apply_to_bundle(bundle, session_id)
                version = io.outbound.scene.version(session_id) or 0
            else:
                version = 0
            assembly.set_slot("scene", narrative=bundle.scene.world_scene.strip(), version=version)
            return
        from .io.inbound.scene import SceneUpdateRequest

        if directive is not None and directive.action == "apply_only":
            io.outbound.scene.apply_to_bundle(bundle, session_id)
            version = io.outbound.scene.version(session_id) or 0
            assembly.set_slot("scene", narrative=bundle.scene.world_scene.strip(), version=version)
            return

        force = directive.force if directive is not None else False
        io.inbound.scene.sync_for_turn(
            SceneUpdateRequest(
                session_id=session_id,
                turn_index=turn_index,
                query=query,
                force=force,
            ),
            force=force,
        )
        io.outbound.scene.apply_to_bundle(bundle, session_id)
        version = io.outbound.scene.version(session_id) or 0
        assembly.set_slot("scene", narrative=bundle.scene.world_scene.strip(), version=version)

    def _run_guidance(
        self,
        bundle: SpeakPromptBundle,
        *,
        assembly: TurnComposeAssembly,
        session_id: str,
        turn_index: int,
        io: OrchestratorIOHub,
        share_queue_count: int,
        share_state: ShareComposeState | None,
        use_session_share_queue: bool,
        pop_presence_share_at: Callable[[str, int], bool] | None,
        pop_session_share_at: Callable[[str, int], bool] | None,
        mark_recall_unit_consumed: Callable[[str, str], None] | None,
        plan: ComposeReconcilePlan | None,
    ) -> None:
        directive = plan.directive_for("guidance") if plan is not None else None
        if directive is not None and directive.action == "apply_only":
            io.outbound.guidance.apply_to_bundle(bundle, session_id)
            control = io.inbound.guidance.control.active(session_id)
            version = io.outbound.guidance.version(session_id) or 0
            narrative = control.narrative.strip() if control is not None else ""
            assembly.set_slot("guidance", narrative=narrative, version=version)
            return

        distilled = _distilled_context(bundle)
        share_candidates = ()
        share_preview = bundle.guidance.share_preview.strip()
        if share_state is not None and share_state.events:
            share_candidates = select_share_candidates(share_state.events)
            share_preview = format_share_candidates(
                share_candidates,
                summary=share_state.summary,
            )
            bundle.guidance.share_preview = share_preview

        persona_brief = collect_persona_outbound_brief(
            io,
            session_id=session_id,
            layer=bundle.persona,
        )
        stash_persona_outbound_brief(bundle, persona_brief)

        request = build_guidance_plan_request(
            session_id=session_id,
            turn_index=turn_index,
            distilled_context=distilled,
            persona_brief=persona_brief,
            interactor_portrait=bundle.guidance.interactor_portrait.strip(),
            share_preview=share_preview,
            recall_preview=bundle.guidance.recall_preview.strip(),
            share_candidates=share_candidates,
            recall_candidates=_recall_candidates_from_bundle(bundle),
            share_queue_count=share_queue_count,
            share_queue_full=io.inbound.guidance.share_queue_full(share_queue_count),
            use_session_share_queue=use_session_share_queue,
        )
        force = directive.force if directive is not None else False
        io.inbound.guidance.sync_for_compose(request, force=force)
        io.outbound.guidance.apply_to_bundle(bundle, session_id)

        control = io.inbound.guidance.control.active(session_id)
        version = io.outbound.guidance.version(session_id) or 0
        narrative = ""
        if control is not None:
            narrative = control.narrative.strip()
        assembly.set_slot("guidance", narrative=narrative, version=version)

        if control is None:
            return
        notes = consume_guidance_emits(
            session_id,
            control,
            pop_presence_share_at=pop_presence_share_at,
            pop_session_share_at=pop_session_share_at,
            use_session_share_queue=use_session_share_queue,
            mark_recall_unit_consumed=mark_recall_unit_consumed,
        )
        bundle.notes.extend(notes)
