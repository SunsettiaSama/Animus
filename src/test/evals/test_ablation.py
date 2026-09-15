"""消融臂测试：BM25 / 语义代理 / 扩散 / 干扰注入 的排序行为与协议。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evals.memory_humaneness.ablation import (
    KGInterfereBase,
    KGBM25Base,
    KGSemanticBase,
    KGSpreadBase,
    KGStore,
    ablation_factory,
    tokenize,
)

MEMS = [
    {"text": "用户对花生过敏，误食一点就会起疹子。", "focus": "花生过敏",
     "emotion": "紧张", "valence": "negative", "days_ago": 10},
    {"text": "川味馆的招牌是花生酱拌面，用户之前提过想去。", "focus": "川味馆招牌",
     "emotion": "期待", "valence": "positive", "days_ago": 5},
    {"text": "用户的橘猫蓝莓喜欢在晨会时踩键盘。", "focus": "蓝莓踩键盘",
     "emotion": "好笑", "valence": "positive", "days_ago": 20},
    {"text": "用户上个月去了滨江公园，说人太多有点累。", "focus": "滨江公园",
     "emotion": "疲惫", "valence": "neutral", "days_ago": 15},
]


def _store() -> KGStore:
    store = KGStore()
    for m in MEMS:
        store.ingest(m["text"], focus=m["focus"], emotion=m["emotion"],
                     valence=m["valence"], days_ago=m["days_ago"])
    return store


def test_tokenize_chinese_bigrams():
    assert "花生" in tokenize("用户对花生过敏")
    assert "过敏" in tokenize("用户对花生过敏")


def test_bm25_ranks_relevant_nodes_first():
    store = _store()
    ranked = KGBM25Base(store)._rank("川味馆点菜要注意什么")
    assert ranked[0][0] == 1  # 招牌那条第一
    assert store.nodes[ranked[0][0]].text.index("花生酱") >= 0


def test_semantic_proxy_ranks_allergen_memory():
    store = _store()
    ranked = KGSemanticBase(store)._rank("花生过敏的人点菜注意")
    top_texts = [store.nodes[i].text for i, _ in ranked[:2]]
    assert any("花生过敏" in t for t in top_texts)


def test_spread_reaches_neighbor_via_edges():
    store = _store()
    ranked = KGSpreadBase(store)._rank("川味馆点菜要注意什么")
    reached = {store.nodes[i].text for i, _ in ranked}
    # 种子：招牌；扩散：过敏（与招牌共享"花生"bigram，实体共现边连通，第2名低分浮出）
    assert any("花生过敏" in t for t in reached)
    assert ranked[0][1] > ranked[1][1]  # 种子分高于传播分


def test_interfere_emotion_boost_promotes_emotional_memory():
    """同词面竞争（两条都含花生）下，情绪烈度高的记忆应被加成顶到第一。"""
    store = KGStore()
    store.ingest("用户提起花生酱的时候语气很平静，聊了两句。", focus="花生酱闲聊",
                 emotion="平静", valence="neutral", days_ago=3)
    store.ingest("用户花生过敏发作，强烈不安，连夜去了急诊。", focus="花生过敏",
                 emotion="崩溃，难受，强烈不安", valence="negative", days_ago=3)
    base = KGInterfereBase(store, seed=42)
    ranked = base._rank("又提到花生相关的事了")
    top_text = store.nodes[ranked[0][0]].text
    assert "花生过敏" in top_text  # 情绪加成把高烈度记忆顶到第一


def test_interfere_recovers_constraint_case():
    """L4 constraint 型：问句无过敏原词面。BM25 只命中招牌；干扰臂的
    关联扰动是随机探索（真实 L4 上 0→0.33 的来源），这里只锁定确定行为：
    招牌第一、结果非空、无异常。"""
    store = KGStore()
    for m in MEMS[:2]:
        store.ingest(m["text"], focus=m["focus"], emotion=m["emotion"],
                     valence=m["valence"], days_ago=m["days_ago"])
    base = KGInterfereBase(store, seed=7)
    ranked = base._rank("晚上约在川味馆吃饭，我点菜有什么要注意的吗？")
    assert ranked
    assert "川味馆" in store.nodes[ranked[0][0]].text


def test_factory_and_port_protocol():
    for kind in ("kg_semantic", "kg_bm25", "kg_spread", "kg_interfere"):
        base = ablation_factory(kind)()
        uid = base.ingest("一条记忆", focus="f", emotion="开心", valence="positive", days_ago=2)
        assert isinstance(uid, str)
        block = base.recall("一条记忆", top_k=3)
        assert hasattr(block, "entries")
        assert isinstance(base.search("hybrid", query="记忆"), list)
        base.dispose()


def test_fresh_factory_per_case_no_pollution():
    f = ablation_factory("kg_bm25")
    b1, b2 = f(), f()
    b1.ingest("甲的记忆", focus="甲")
    assert len(b2._store) == 0  # 全新存储，零污染
