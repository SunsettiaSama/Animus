from __future__ import annotations

from agent.soul.memory.domain import MemoryNetwork
from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.graph.seeds import SeedResolver


class _NodeStore:
    def __init__(self, nodes):
        self._nodes = list(nodes)

    def list_by_network(self, network, *, limit: int = 50):
        return [n for n in self._nodes if n.network == network][:limit]


def _node(node_id: str, text: str) -> FactualMemory:
    return FactualMemory(id=node_id, focus=text, fact=text, base_activation=0.5)


def _resolver(nodes):
    return SeedResolver(_NodeStore(nodes), None, keyword_weight=0.55, seed_top_k=8)


def test_entity_hit_scores_above_keyword():
    ramen = _node("ramen", "上次一起去的拉面店在巷子深处")
    other = _node("other", "那本书看完了")
    seeds = _resolver([ramen, other]).resolve(
        "还记得拉面店",
        networks=(MemoryNetwork.event,),
        entities=["拉面店"],
    )
    assert seeds.get("ramen") == SeedResolver.ENTITY_SEED_SCORE
    assert "other" not in seeds


def test_entity_overrides_keyword_score_for_same_node():
    ramen = _node("ramen", "拉面店很好吃")
    # 同一节点既命中关键词又命中实体 → 取实体高分
    seeds = _resolver([ramen]).resolve(
        "拉面店",
        networks=(MemoryNetwork.event,),
        entities=["拉面店"],
    )
    assert seeds["ramen"] == SeedResolver.ENTITY_SEED_SCORE

    no_entity = _resolver([ramen]).resolve(
        "拉面店",
        networks=(MemoryNetwork.event,),
    )
    assert no_entity["ramen"] == 0.55  # 仅关键词命中给 keyword_weight


def test_no_entities_falls_back_to_keyword_behavior():
    ramen = _node("ramen", "拉面店很好吃")
    seeds = _resolver([ramen]).resolve(
        "拉面店",
        networks=(MemoryNetwork.event,),
        entities=[],
    )
    assert seeds == {"ramen": 0.55}


def test_entity_miss_keeps_keyword_hits():
    ramen = _node("ramen", "拉面店很好吃")
    seeds = _resolver([ramen]).resolve(
        "拉面店",
        networks=(MemoryNetwork.event,),
        entities=["不存在的实体"],
    )
    assert seeds == {"ramen": 0.55}
