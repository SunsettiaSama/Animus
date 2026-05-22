from __future__ import annotations

import pytest

from agent.soul.handlers.api.actions import LifeAction, MemoryAction, PersonaAction
from agent.soul.request import SoulChannel, SoulDomain, SoulRequest


def test_idle_allows_read_rejects_write(soul_service):
    snap = soul_service.query_persona()
    assert isinstance(snap, dict)
    assert soul_service.state == "idle"

    with pytest.raises(RuntimeError, match="未运行"):
        soul_service.dispatch(SoulRequest(
            domain=SoulDomain.memory,
            action=MemoryAction.FORGET_SCAN,
        ))


def test_start_stop_lifecycle(soul_service):
    soul_service.start()
    assert soul_service.state == "running"
    assert soul_service.status()["state"] == "running"

    soul_service.stop()
    assert soul_service.state == "stopped"

    with pytest.raises(RuntimeError, match="已 stop"):
        soul_service.start()

    with pytest.raises(RuntimeError, match="已停止"):
        soul_service.query_persona()


def test_running_write_and_life_reads(soul_service):
    soul_service.start()

    result = soul_service.record_persona_interaction("你好", "你好呀")
    assert result.get("applied") is False
    assert "Presence" in str(result.get("reason", ""))
    chronicle = soul_service.query_life_chronicle(days=1, tail=10)
    hot = soul_service.query_life_hot()
    memory = soul_service.search_memory(mode="recent", top_k=3)

    assert isinstance(chronicle, list)
    assert isinstance(hot, list)
    assert memory["mode"] == "recent"
    assert "results" in memory

    soul_service.stop()


def test_query_persona_matches_dispatch(soul_service):
    soul_service.start()
    via_query = soul_service.query_persona()
    via_dispatch = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.persona,
        action=PersonaAction.GET_SNAPSHOT,
    ))
    assert via_query["profile"] == via_dispatch["profile"]
    assert via_query["self_concept"] == via_dispatch["self_concept"]
    assert "presence_affect" in via_query
    soul_service.stop()


def test_search_memory_matches_dispatch(soul_service):
    soul_service.start()
    via_query = soul_service.search_memory(mode="recent", top_k=2)
    via_dispatch = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.memory,
        action=MemoryAction.SEARCH,
        payload={"mode": "recent", "top_k": 2},
    ))
    assert via_query == via_dispatch
    soul_service.stop()


def test_life_chronicle_matches_dispatch(soul_service):
    soul_service.start()
    via_query = soul_service.query_life_chronicle(days=3, tail=5)
    via_dispatch = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.life,
        action=LifeAction.RECENT_CHRONICLE,
        payload={"days": 3, "tail": 5},
    ))
    assert via_query == via_dispatch
    soul_service.stop()


def test_tao_channel_requires_running(soul_service):
    from agent.soul.handlers.tao.actions import TaoPersonaAction

    with pytest.raises(RuntimeError, match="未运行"):
        soul_service.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=TaoPersonaAction.RUN,
            channel=SoulChannel.tao,
            payload={"instruction": "test", "profile_name": "default"},
        ))
