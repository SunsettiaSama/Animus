from __future__ import annotations

from agent.soul.memory.emergence.session_results import KeywordFieldResult
from agent.soul.memory.graph.field_keyword import FieldKeywordQueryEngine

from ..deps import SessionIODeps
from ..request import KeywordQueryInbound


def run_keyword_field_query(
    deps: SessionIODeps,
    inbound: KeywordQueryInbound,
    *,
    engine: FieldKeywordQueryEngine | None = None,
) -> KeywordFieldResult:
    sid = inbound.session_id.strip()
    iid = inbound.interactor_id.strip()
    text = inbound.user_text.strip()
    if not text:
        return KeywordFieldResult(
            session_id=sid,
            interactor_id=iid,
            turn_index=inbound.turn_index,
        )

    query_engine = engine or FieldKeywordQueryEngine(
        deps.social._nodes,
        half_life_days=deps.cfg.recent_half_life_days,
    )
    top_k = max(1, deps.cfg.speak_compose_memory_budget)
    scored = query_engine.query(
        text,
        interactor_id=iid,
        top_k=top_k,
    )
    cap = deps.cfg.speak_memory_line_max_content
    lines = [s.render_line(max_content=cap) for s in scored]
    unit_ids = [s.unit.id for s in scored]
    return KeywordFieldResult(
        session_id=sid,
        interactor_id=iid,
        turn_index=inbound.turn_index,
        lines=lines,
        unit_ids=unit_ids,
    )
