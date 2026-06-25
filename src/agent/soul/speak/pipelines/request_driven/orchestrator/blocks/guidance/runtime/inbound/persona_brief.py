from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.persona import PersonaOutboundBrief

if TYPE_CHECKING:
    from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance.runtime.control.state import GuidanceTrigger
    from agent.soul.speak.pipelines.request_driven.orchestrator.bundle import SpeakPromptBundle
    from agent.soul.speak.pipelines.request_driven.orchestrator.io.inbound.guidance import GuidancePlanRequest


def render_persona_planner_blocks(brief: PersonaOutboundBrief) -> list[str]:
    blocks: list[str] = []
    narrative = brief.self_narrative.strip()
    stable = brief.stable_portrait.strip()
    state = brief.state_portrait.strip()
    mood = brief.instant_mood.strip()
    if narrative:
        blocks.append(f"【agent 人设·自叙】\n{narrative}")
    if stable and stable != narrative:
        blocks.append(f"【agent 稳定锚点】\n{stable}")
    if state:
        blocks.append(f"【agent 近期状态源】\n{state}")
    if mood:
        blocks.append(f"【agent 瞬间情绪】\n{mood}")
    if brief.recent_distill_lines:
        joined = "\n".join(f"- {line}" for line in brief.recent_distill_lines)
        blocks.append(f"【agent 过往自叙修订】\n{joined}")
    return blocks


def stash_persona_outbound_brief(
    bundle: SpeakPromptBundle,
    brief: PersonaOutboundBrief,
) -> None:
    bundle.meta["persona_outbound_brief"] = brief


def read_persona_outbound_brief(bundle: SpeakPromptBundle) -> PersonaOutboundBrief | None:
    raw = bundle.meta.get("persona_outbound_brief")
    if isinstance(raw, PersonaOutboundBrief):
        return raw
    return None


def build_guidance_plan_request(
    *,
    session_id: str,
    turn_index: int,
    distilled_context: str,
    persona_brief: PersonaOutboundBrief,
    interactor_portrait: str = "",
    share_preview: str = "",
    recall_preview: str = "",
    share_candidates=(),
    recall_candidates=(),
    share_queue_count: int = 0,
    share_queue_full: bool = False,
    trigger: str = "turn",
    use_session_share_queue: bool = False,
) -> GuidancePlanRequest:
    from agent.soul.speak.pipelines.request_driven.orchestrator.io.inbound.guidance import GuidancePlanRequest

    return GuidancePlanRequest(
        session_id=session_id,
        turn_index=turn_index,
        distilled_context=distilled_context,
        persona_portrait=persona_brief.portrait_for_planner,
        persona_brief=persona_brief,
        interactor_portrait=interactor_portrait,
        share_preview=share_preview,
        recall_preview=recall_preview,
        share_candidates=share_candidates,
        recall_candidates=recall_candidates,
        share_queue_count=share_queue_count,
        share_queue_full=share_queue_full,
        trigger=trigger,
        use_session_share_queue=use_session_share_queue,
    )
