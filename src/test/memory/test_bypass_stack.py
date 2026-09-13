"""增量式 stack 记忆旁路（bypass）单元测试（真实导入链）。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.memory.bypass import StackMemoryService, StackMemoryUnit
from agent.soul.memory.ports import MemoryBasePort


@pytest.fixture()
def svc(tmp_path):
    return StackMemoryService(tmp_path / "stack" / "memory.jsonl")


def _backdated(days_ago: float, **kwargs) -> StackMemoryUnit:
    unit = StackMemoryUnit(**kwargs)
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    unit.created_at = when
    unit.last_accessed = when
    return unit


def test_conforms_to_memory_base_protocol(svc):
    assert isinstance(svc, MemoryBasePort)


def test_ingest_returns_id_and_persists_incrementally(svc, tmp_path):
    path = tmp_path / "stack" / "memory.jsonl"
    uid = svc.ingest("第一条记忆", focus="一", valence="positive")
    assert svc.store.path.is_file()
    first_size = path.stat().st_size
    uid2 = svc.ingest("第二条记忆", focus="二")
    assert uid != uid2
    # 增量追加：第二次 push 只增加一行，不做全量重建
    assert path.stat().st_size > first_size
    assert len(svc) == 2


def test_recent_returns_top_first(svc):
    svc.ingest("旧的", focus="旧")
    svc.ingest("新的", focus="新")
    recent = svc.search("recent", limit=2)
    assert recent[0]["focus"] == "新"
    assert recent[-1]["focus"] == "旧"


def test_recall_ranks_chinese_sentence_by_relevance(svc):
    svc.ingest("用户养了一只叫蓝莓的橘猫", focus="橘猫蓝莓")
    svc.ingest("用户在准备晋升答辩", focus="晋升答辩")
    svc.ingest("上周一起淋雨跑回了家", focus="淋雨")
    block = svc.recall("蓝莓那只猫最近怎么样", top_k=3)
    assert block.label == "旁路记忆"
    assert block.entries
    assert "橘猫蓝莓" in block.entries[0]
    # recall 计数回写并持久化
    assert svc.peek(10)[-1].recall_count == 1


def test_hybrid_min_relevance_filters_noise(svc):
    svc.ingest("用户养了一只叫蓝莓的橘猫", focus="橘猫蓝莓")
    # recall（注入入口）：无关查询返回空块，不注入噪声
    block = svc.recall("量子物理的测不准原理", top_k=3)
    assert block.entries == []
    # search('hybrid')：保持与 QueryEngine 一致的 recent 兜底语义
    assert svc.search("hybrid", query="量子物理的测不准原理", top_k=2)


def test_by_valence_and_by_field(svc):
    svc.ingest("答辩挂了很难过", focus="答辩", valence="negative", emotion="难过")
    svc.ingest("中了奖很开心", focus="中奖", valence="positive", emotion="开心")
    neg = svc.search("by_valence", valence="negative")
    assert [d["focus"] for d in neg] == ["答辩"]
    hits = svc.search("by_field", emotion_contains="开心")
    assert [d["focus"] for d in hits] == ["中奖"]
    assert svc.search("by_field", interactor_id="alice") == []


def test_semantic_mode_requires_embedder(svc):
    with pytest.raises(RuntimeError):
        svc.search("semantic", query=" anything ")


def test_semantic_mode_with_fake_embedder(svc):
    def embed(text: str) -> list[float]:
        table = {"猫": [1.0, 0.0], "狗": [0.0, 1.0]}
        vec = [0.0, 0.0]
        for key, vec_k in table.items():
            if key in text:
                vec[0] += vec_k[0]
                vec[1] += vec_k[1]
        return vec or [0.0, 0.0]

    svc2 = StackMemoryService(svc.store.path, embedder=embed)
    svc2.ingest("一只猫", focus="猫")
    svc2.ingest("一条狗", focus="狗")
    hits = svc2.search("semantic", query="猫科动物", top_k=2)
    assert hits[0]["focus"] == "猫"


def test_eviction_trims_bottom(svc):
    for i in range(6):
        svc.ingest(f"记忆{i}", focus=f"mem{i}")
    reloaded = StackMemoryService(svc.store.path, max_entries=5)
    assert len(reloaded) == 5
    focuses = [u.focus for u in reloaded.peek(10)]
    assert focuses[0] == "mem5"  # 栈顶最新
    assert "mem0" not in focuses  # 栈底最旧被淘汰


def test_backdating_visible_to_by_field(svc):
    svc.push(_backdated(30.0, focus="旧事", content="很久以前的事"))
    svc.ingest("昨天的事", focus="昨")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    old = svc.search("by_field", created_before=cutoff)
    assert [d["focus"] for d in old] == ["旧事"]
    assert old[0]["network"] == "stack"


def test_network_tag_isolation():
    unit = StackMemoryUnit(focus="f", content="c")
    assert unit.NODE_KIND == "stack"
    assert unit.network.value == "stack"
    # 渲染行使用旁路专属标签，与 event/social 记忆可区分
    from agent.soul.memory.domain.labels import memory_kind_prompt_label

    assert memory_kind_prompt_label("stack") == "旁路的记忆"


def test_clear(svc):
    svc.ingest("一条")
    assert svc.clear() == 1
    assert len(svc) == 0
