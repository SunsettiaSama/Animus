from __future__ import annotations

from agent.soul.memory.domain.enums import SocialNodeRole
from agent.soul.memory.graph.networks.archival import ExperienceArchiver
from agent.soul.memory.graph.networks.social.interactor_resolve import (
    probe_interactor_core,
    render_interactor_portrait_block,
    resolve_likely_interactor_core,
)
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.graph.networks.social.query import SocialQueryEngine
from test.memory.networks.test_social_network import _EdgeStore, _FakeLLM, _InteractorStore, _MemStore


def test_resolve_interactor_by_user_tone():
    nodes = _MemStore()
    edges = _EdgeStore()
    social = SocialMemoryNetwork(
        nodes,
        edges,
        _InteractorStore(),
        ExperienceArchiver(_FakeLLM({}), nodes),
        query=SocialQueryEngine(nodes),
    )
    social.register_core_portrait(
        "alice",
        {"name": "Alice", "core_traits": ["健谈"], "background_facts": ["产品经理"]},
        agent_relation="我觉得她表达清晰",
    )
    social.register_core_portrait(
        "bob",
        {"name": "Bob", "core_traits": ["内向"]},
    )
    iid, core = resolve_likely_interactor_core(
        social,
        "Alice 今天聊了很多产品需求，语气很专业",
        hinted_interactor_id="",
    )
    assert iid == "alice"
    assert core is not None
    block = render_interactor_portrait_block(iid, core)
    assert "Alice" in block
    assert "产品经理" in block or "健谈" in block
    assert "表达清晰" in block


def test_ambiguous_probe_returns_empty():
    nodes = _MemStore()
    social = SocialMemoryNetwork(
        nodes,
        _EdgeStore(),
        _InteractorStore(),
        ExperienceArchiver(_FakeLLM({}), nodes),
        query=SocialQueryEngine(nodes),
    )
    social.register_core_portrait("alice", {"name": "Alice"})
    social.register_core_portrait("bob", {"name": "Bob"})
    probe = probe_interactor_core(
        social,
        "你好",
        hinted_interactor_id="",
        min_best_score=0.99,
        max_score_gap=0.99,
    )
    assert probe.ambiguous
    iid, core = resolve_likely_interactor_core(social, "你好", hinted_interactor_id="")
    assert iid == ""
    assert core is None


def test_hinted_interactor_short_circuit():
    nodes = _MemStore()
    social = SocialMemoryNetwork(
        nodes,
        _EdgeStore(),
        _InteractorStore(),
        ExperienceArchiver(_FakeLLM({}), nodes),
    )
    social.ensure_core("carol")
    iid, core = resolve_likely_interactor_core(social, "随便一句", hinted_interactor_id="carol")
    assert iid == "carol"
    assert core is not None
    assert core.interactor_id == "carol"
