from __future__ import annotations

from agent.soul.memory.domain import (
    EdgeType,
    EvolutionSource,
    FactualMemory,
    MemoryEdge,
    SocialCoreNode,
    SocialNeighborhoodNode,
    Valence,
)
from agent.soul.memory.networks.social.core_evolution import CoreEvolver


def test_factual_memory_activation_increases_with_recall():
    mem = FactualMemory(focus="test", fact="x", perception="y", base_activation=0.5)
    base = mem.activation(half_life_days=30.0)
    mem.on_recall()
    boosted = mem.activation(half_life_days=30.0)
    assert boosted >= base


def test_core_evolver_appends_delta():
    core = SocialCoreNode(interactor_id="alice", focus="印象", core_traits="")
    evolved = CoreEvolver().evolve(core, delta="我觉得他是个好人", source=EvolutionSource.manual)
    assert evolved.trait_version == 2
    assert "好人" in evolved.core_traits


def test_social_neighborhood_fields():
    node = SocialNeighborhoodNode(
        interactor_id="alice",
        focus="宠物",
        label="猫",
        content="叫小黑",
    )
    assert node.network.value == "social"
    assert "小黑" in node.embed_text()
