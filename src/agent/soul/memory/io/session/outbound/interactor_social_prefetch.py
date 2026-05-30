from __future__ import annotations

from agent.soul.memory.emergence.session_results import InteractorSocialPrefetchResult
from agent.soul.memory.graph.networks.social.node import SocialCoreNode

from ..deps import SessionIODeps
from ..request import InteractorPrefetchInbound


def _prefetch_query_text(deps: SessionIODeps, interactor_id: str) -> str:
    display_name = interactor_id
    if interactor_id.strip():
        direct = deps.social._nodes.get_core_for_interactor(interactor_id.strip())
        if isinstance(direct, SocialCoreNode):
            name = direct.portrait.name.strip()
            if name:
                display_name = name
    return f"与{display_name}相关的社交记忆"


def run_interactor_social_prefetch(
    deps: SessionIODeps,
    inbound: InteractorPrefetchInbound,
) -> InteractorSocialPrefetchResult:
    iid = inbound.interactor_id.strip()
    sid = inbound.session_id.strip()
    if not iid:
        return InteractorSocialPrefetchResult(
            session_id=sid,
            interactor_id=iid,
            turn_index=inbound.turn_index,
        )

    query = _prefetch_query_text(deps, iid)
    top_k = max(1, deps.cfg.recall_top_k)
    scored = deps.social._query.hybrid(query, top_k=top_k, interactor_id=iid)
    cap = deps.cfg.speak_memory_line_max_content
    lines = [s.render_line(max_content=cap) for s in scored]
    unit_ids = [s.unit.id for s in scored]
    return InteractorSocialPrefetchResult(
        session_id=sid,
        interactor_id=iid,
        turn_index=inbound.turn_index,
        lines=lines,
        unit_ids=unit_ids,
    )
