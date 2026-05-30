from __future__ import annotations

from agent.soul.memory.facade.interactor_portrait import InteractorPortraitSpeakResult
from agent.soul.memory.graph.networks.social.node import SocialCoreNode

from ..deps import SessionIODeps
from ..request import DialogueTurnInbound


def run_dynamic_portrait(
    deps: SessionIODeps,
    inbound: DialogueTurnInbound,
) -> InteractorPortraitSpeakResult:
    """对话轮次实时画像：已知 interactor 直达 core，否则语义 probe（与 facade 原逻辑一致）。"""
    user = inbound.user_text.strip()
    agent = inbound.agent_text.strip()
    query = "\n".join(part for part in (user, agent) if part)
    channel_id = (inbound.channel_id or inbound.session_id).strip()
    hinted = inbound.interactor_id.strip()
    bound = hinted or deps.resolve_channel_interactor(channel_id)

    interactor_id = ""
    core = None
    if bound:
        direct = deps.social._nodes.get_core_for_interactor(bound)
        if isinstance(direct, SocialCoreNode):
            interactor_id = bound
            core = direct
    elif query:
        probe = deps.social.probe_interactor_for_tone(
            query,
            hinted_interactor_id="",
            min_best_score=deps.cfg.portrait_probe_min_score,
            max_score_gap=deps.cfg.portrait_probe_max_score_gap,
        )
        if not probe.ambiguous and probe.core is not None and probe.interactor_id:
            interactor_id = probe.interactor_id
            core = probe.core
            deps.bind_session_channel(channel_id, interactor_id)

    display_name = ""
    core_traits: tuple[str, ...] = ()
    portrait_body = ""
    agent_relation = ""
    recent_impression = ""
    if isinstance(core, SocialCoreNode):
        display_name = core.portrait.name.strip()
        core_traits = tuple(
            t.strip() for t in core.portrait.core_traits if t.strip()
        )
        portrait_body = core.portrait.render().strip()
        agent_relation = core.agent_relation.strip()
        changelog = core.trait_changelog.strip()
        if changelog:
            recent_impression = changelog.splitlines()[-1].strip()

    return InteractorPortraitSpeakResult(
        session_id=inbound.session_id.strip(),
        turn_index=inbound.turn_index,
        interactor_id=interactor_id,
        portrait_text="",
        display_name=display_name,
        core_traits=core_traits,
        portrait_body=portrait_body,
        agent_relation=agent_relation,
        recent_impression=recent_impression,
    )
