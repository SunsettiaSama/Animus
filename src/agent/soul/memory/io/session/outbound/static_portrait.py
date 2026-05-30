from __future__ import annotations

from agent.soul.memory.facade.interactor_portrait import InteractorPortraitSpeakResult
from agent.soul.memory.graph.networks.social.node import SocialCoreNode

from ..deps import SessionIODeps


def load_static_core_portrait(
    deps: SessionIODeps,
    *,
    interactor_id: str,
    session_id: str,
    turn_index: int = 0,
) -> InteractorPortraitSpeakResult:
    """账号/渠道绑定后：直达 SocialCore 静态画像（无语义 probe）。"""
    iid = interactor_id.strip()
    sid = session_id.strip()
    display_name = ""
    core_traits: tuple[str, ...] = ()
    portrait_body = ""
    agent_relation = ""
    recent_impression = ""
    if iid:
        direct = deps.social._nodes.get_core_for_interactor(iid)
        if isinstance(direct, SocialCoreNode):
            display_name = direct.portrait.name.strip()
            core_traits = tuple(
                t.strip() for t in direct.portrait.core_traits if t.strip()
            )
            portrait_body = direct.portrait.render().strip()
            agent_relation = direct.agent_relation.strip()
            changelog = direct.trait_changelog.strip()
            if changelog:
                recent_impression = changelog.splitlines()[-1].strip()
    return InteractorPortraitSpeakResult(
        session_id=sid,
        turn_index=turn_index,
        interactor_id=iid,
        portrait_text="",
        display_name=display_name,
        core_traits=core_traits,
        portrait_body=portrait_body,
        agent_relation=agent_relation,
        recent_impression=recent_impression,
    )
