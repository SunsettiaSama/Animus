from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.memory.io.session.outbound.interactor_social_prefetch import (
    run_interactor_social_prefetch,
)
from agent.soul.memory.io.session.request import InteractorPrefetchInbound


def test_interactor_social_prefetch_empty_interactor():
    deps = MagicMock()
    result = run_interactor_social_prefetch(
        deps,
        InteractorPrefetchInbound(session_id="s1", interactor_id=""),
    )
    assert result.unit_ids == []


def test_interactor_social_prefetch_hybrid_results():
    deps = MagicMock()
    deps.cfg.recall_top_k = 3
    deps.social._nodes.get_core_for_interactor.return_value = None
    unit = MagicMock()
    unit.id = "u1"
    scored = MagicMock()
    scored.render_line.return_value = "line-1"
    scored.unit = unit
    deps.social._query.hybrid.return_value = [scored]

    result = run_interactor_social_prefetch(
        deps,
        InteractorPrefetchInbound(session_id="s1", interactor_id="i1"),
    )
    assert result.unit_ids == ["u1"]
    assert result.lines == ["line-1"]
