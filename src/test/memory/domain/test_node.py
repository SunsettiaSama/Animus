from __future__ import annotations

from agent.soul.memory.domain import (
    EvolutionSource,
    FactualMemory,
    SocialCoreNode,
    SocialNeighborhoodNode,
)
from agent.soul.memory.graph.node.modify.evolve import CoreEvolver
from agent.soul.memory.graph.networks.social.portrait import InteractorPortrait


def test_factual_memory_activation_increases_with_recall():
    mem = FactualMemory(focus="test", fact="x", perception="y", base_activation=0.5)
    base = mem.activation(half_life_days=30.0)
    mem.on_recall()
    boosted = mem.activation(half_life_days=30.0)
    assert boosted >= base


def test_core_evolver_appends_delta():
    core = SocialCoreNode(
        interactor_id="alice",
        focus="?alice???",
        portrait=InteractorPortrait(name="Alice"),
    )
    evolved = CoreEvolver().evolve(
        core,
        delta="???????",
        source=EvolutionSource.manual,
    )
    assert evolved.trait_version == 2
    assert "???????" in evolved.trait_changelog


def test_social_neighborhood_fields():
    node = SocialNeighborhoodNode(
        interactor_id="alice",
        focus="pets",
        label="cat",
        content="??????",
        related_interactor_ids=["bob"],
    )
    assert node.network.value == "social"
    assert "??" in node.embed_text()
    assert "bob" in node.embed_text()
