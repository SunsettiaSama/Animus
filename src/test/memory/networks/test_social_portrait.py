from __future__ import annotations

from agent.soul.memory.domain import EdgeType, EvolutionSource
from agent.soul.memory.graph.networks.archival import ExperienceArchiver
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.graph.networks.social.portrait import InteractorPortrait
from agent.soul.memory.graph.networks.social.query import SocialQueryEngine
from agent.soul.memory.graph.networks.social.node import SocialCoreNode, SocialNeighborhoodNode
from test.memory.networks.test_social_network import _EdgeStore, _FakeLLM, _InteractorStore, _MemStore


def test_register_core_portrait_and_agent_relation():
    nodes = _MemStore()
    edges = _EdgeStore()
    social = SocialMemoryNetwork(
        nodes,
        edges,
        _InteractorStore(),
        ExperienceArchiver(_FakeLLM({}), nodes),
    )
    core = social.register_core_portrait(
        "alice",
        {
            "name": "Alice",
            "core_traits": ["健谈", "细心"],
            "background_facts": ["在互联网公司做产品"],
        },
        agent_relation="我觉得她愿意倾听，也值得信赖",
        display_name="Alice",
    )
    assert isinstance(core, SocialCoreNode)
    assert core.portrait.name == "Alice"
    assert "健谈" in core.portrait.core_traits
    assert "值得信赖" in core.agent_relation
    assert core.embed_text_cache
    assert core.embedding == []


def test_link_interactor_relation_connects_cores():
    nodes = _MemStore()
    edges = _EdgeStore()
    social = SocialMemoryNetwork(
        nodes,
        edges,
        _InteractorStore(),
        ExperienceArchiver(_FakeLLM({}), nodes),
    )
    social.register_core_portrait("alice", {"name": "Alice"})
    social.register_core_portrait("bob", {"name": "Bob"})
    relation = social.link_interactor_relation(
        "alice",
        "bob",
        label="好友",
        content="Alice 和 Bob 是多年好友，常一起讨论产品",
    )
    assert isinstance(relation, SocialNeighborhoodNode)
    assert "bob" in relation.related_interactor_ids
    assert any(e.edge_type == EdgeType.related_to for e in edges.edges)
    assert any(e.edge_type == EdgeType.about for e in edges.edges)


def test_social_hybrid_recall_prefers_matching_content():
    nodes = _MemStore()
    edges = _EdgeStore()
    social = SocialMemoryNetwork(
        nodes,
        edges,
        _InteractorStore(),
        ExperienceArchiver(_FakeLLM({}), nodes),
        query=SocialQueryEngine(nodes),
    )
    social.add_supplement(
        "alice",
        label="宠物",
        content="她养了一只橘猫，叫小橘子",
    )
    social.add_supplement(
        "alice",
        label="工作",
        content="最近在准备晋升答辩",
    )
    block = social.recall("橘猫", top_k=2, interactor_id="alice")
    assert "橘猫" in "\n".join(block.entries) or "橘子" in "\n".join(block.entries)


def test_core_evolver_appends_trait_changelog():
    nodes = _MemStore()
    edges = _EdgeStore()
    social = SocialMemoryNetwork(
        nodes,
        edges,
        _InteractorStore(),
        ExperienceArchiver(_FakeLLM({}), nodes),
    )
    social.register_core_portrait("alice", {"name": "Alice"})
    evolved = social.evolve_core(
        "alice",
        delta="更愿意分享情绪",
        source=EvolutionSource.manual,
    )
    assert evolved.trait_version == 2
    assert "更愿意分享情绪" in evolved.trait_changelog
