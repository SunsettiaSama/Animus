"""
LongTermStore — Qdrant 后端单元测试
=====================================
使用 MagicMock 桩住 QdrantClient 和 Embedder，在不依赖任何外部服务
（无网络、无磁盘 Qdrant、无 BGE 模型、无 torch）的前提下，验证：

  add()               → 正确 upsert 到 Qdrant
  search_with_scores()→ 正确调用 query_points 并格式化结果
  recall()            → 正确调用 query_points 并裁剪长度
  save()              → 只写 memories.json，不写 Qdrant 文件
  preload()           → 点数一致时不重建；不一致时调用 rebuild_index
  rebuild_index()     → 批量 embed + upsert 全部 entries
  _ensure_collection()→ 已存在时不重复创建；不存在时创建

运行方式：
  cd E:/ReAct
  python -m pytest src/test/test_ltm_qdrant.py -v
  # 或直接：
  python src/test/test_ltm_qdrant.py
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

SRC = Path(__file__).resolve().parent.parent.parent
REACT_DIR = SRC / "agent" / "react"


# ── stubs（必须在任何项目模块导入之前注册）───────────────────────────────────────

def _pkg_stub(dotted_name: str, path: Path | None = None) -> types.ModuleType:
    m = types.ModuleType(dotted_name)
    m.__package__ = dotted_name
    m.__spec__ = importlib.machinery.ModuleSpec(
        dotted_name, loader=None, is_package=True
    )
    if path is not None:
        m.__path__ = [str(path)]
        m.__spec__.submodule_search_locations = m.__path__
    sys.modules[dotted_name] = m
    return m


def _mod_stub(dotted_name: str) -> types.ModuleType:
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


_pkg_stub("agent.react", REACT_DIR)

_qdrant = _pkg_stub("qdrant_client")
_qdrant_models = _mod_stub("qdrant_client.models")
_qdrant.QdrantClient = MagicMock(name="QdrantClient")
for _mn in ("Distance", "FieldCondition", "Filter", "FilterSelector",
            "MatchValue", "PointIdsList", "PointStruct", "VectorParams"):
    setattr(_qdrant_models, _mn, MagicMock(name=_mn))
_qdrant.models = _qdrant_models

_emb_pkg = _pkg_stub("embedding")
_emb_embedder_mod = _mod_stub("embedding.embedder")
_emb_embedder_mod.Embedder = MagicMock(name="Embedder")
_emb_embedder_mod.infer_dim = MagicMock(name="infer_dim", return_value=512)
_emb_pkg.embedder = _emb_embedder_mod

sys.path.insert(0, str(SRC))

# ── 真实模块导入（stubs 已就位）──────────────────────────────────────────────────

from config.agent.memory.memory_config import LongTermMemoryConfig
from agent.react.memory.long_term.store import LongTermStore, MemoryEntry, MEMORIES_FILE


# ── 辅助工厂 ──────────────────────────────────────────────────────────────────

def _make_cfg(**kw) -> LongTermMemoryConfig:
    return LongTermMemoryConfig(
        enabled=True,
        load_from_disk=False,
        memory_dir=kw.pop("memory_dir", ".test_mem"),
        qdrant_path=kw.pop("qdrant_path", ".test_mem/qdrant"),
        collection_name=kw.pop("collection_name", "test_collection"),
        **kw,
    )


def _make_store(entries=None, **cfg_kw) -> LongTermStore:
    return LongTermStore(entries=entries or [], cfg=_make_cfg(**cfg_kw))


def _make_mock_client(collection_names: list[str] | None = None, point_count: int = 0):
    """返回一个模拟 QdrantClient，预设集合列表和点数。"""
    client = MagicMock(name="QdrantClient_instance")

    # get_collections 返回值
    coll_obj = MagicMock()
    existing = collection_names or []
    coll_obj.collections = [MagicMock(name=n) for n in existing]
    # 每个 mock collection 的 .name 属性
    for mock_c, n in zip(coll_obj.collections, existing):
        mock_c.name = n
    client.get_collections.return_value = coll_obj

    # get_collection 返回值（用于 preload 检查点数）
    info = MagicMock()
    info.points_count = point_count
    client.get_collection.return_value = info

    # query_points 返回空列表（子测试按需覆盖）
    qr = MagicMock()
    qr.points = []
    client.query_points.return_value = qr

    return client


def _make_mock_embedder(dim: int = 512):
    emb = MagicMock(name="Embedder_instance")
    emb.embed_documents.side_effect = lambda texts: [[0.1] * dim for _ in texts]
    emb.embed_query.return_value = [0.2] * dim
    return emb


def _inject_store(store: LongTermStore, mock_client, mock_embedder):
    """直接注入 mock，跳过懒加载。"""
    store._client = mock_client
    store._embedder = mock_embedder
    store._collection_ready = True


# ── _ensure_collection ────────────────────────────────────────────────────────

def test_ensure_collection_creates_when_missing():
    """集合不存在时应调用 create_collection。"""
    store = _make_store()
    client = _make_mock_client(collection_names=[])  # 空集合列表
    store._client = client
    store._embedder = _make_mock_embedder()

    store._ensure_collection()

    client.create_collection.assert_called_once()
    call_kw = client.create_collection.call_args.kwargs
    assert call_kw["collection_name"] == "test_collection"
    assert store._collection_ready is True
    print("[OK] test_ensure_collection_creates_when_missing")


def test_ensure_collection_skips_when_exists():
    """集合已存在时不应调用 create_collection。"""
    store = _make_store()
    client = _make_mock_client(collection_names=["test_collection"])
    store._client = client
    store._embedder = _make_mock_embedder()

    store._ensure_collection()

    client.create_collection.assert_not_called()
    assert store._collection_ready is True
    print("[OK] test_ensure_collection_skips_when_exists")


def test_ensure_collection_idempotent():
    """_collection_ready=True 后再次调用不应查询 Qdrant。"""
    store = _make_store()
    client = _make_mock_client()
    _inject_store(store, client, _make_mock_embedder())

    store._ensure_collection()  # _collection_ready 已为 True
    client.get_collections.assert_not_called()
    print("[OK] test_ensure_collection_idempotent")


# ── add ──────────────────────────────────────────────────────────────────────

def test_add_upserts_to_qdrant():
    """add() 应向 Qdrant upsert 一个 PointStruct，并追加到 _entries。"""
    store = _make_store()
    client = _make_mock_client(collection_names=["test_collection"])
    embedder = _make_mock_embedder()
    _inject_store(store, client, embedder)

    entry = store.add("hello world", source="test")

    assert len(store._entries) == 1
    assert store._entries[0].text == "hello world"
    assert store._entries[0].id == entry.id

    client.upsert.assert_called_once()
    upsert_kw = client.upsert.call_args.kwargs
    assert upsert_kw["collection_name"] == "test_collection"
    assert len(upsert_kw["points"]) == 1

    embedder.embed_documents.assert_called_once_with(["hello world"])
    print("[OK] test_add_upserts_to_qdrant")


def test_add_truncates_long_text():
    """超出 max_entry_chars 的文本应被截断后再存入。"""
    store = _make_store(max_entry_chars=10)
    _inject_store(store, _make_mock_client(collection_names=["test_collection"]), _make_mock_embedder())

    entry = store.add("A" * 50)

    assert len(entry.text) == 10
    assert entry.text == "A" * 10
    print("[OK] test_add_truncates_long_text")


def test_add_returns_memory_entry():
    """add() 应返回包含 id、text、created_at 的 MemoryEntry。"""
    store = _make_store()
    _inject_store(store, _make_mock_client(collection_names=["test_collection"]), _make_mock_embedder())

    entry = store.add("test text")

    assert isinstance(entry, MemoryEntry)
    assert entry.text == "test text"
    assert entry.id
    assert entry.created_at
    print("[OK] test_add_returns_memory_entry")


# ── search_with_scores ────────────────────────────────────────────────────────

def _make_hit(text: str, created_at: str, score: float):
    hit = MagicMock()
    hit.score = score
    hit.payload = {"text": text, "created_at": created_at}
    return hit


def test_search_with_scores_calls_query_points():
    """search_with_scores 应调用 query_points 并返回正确格式的 (score, text) 列表。"""
    store = _make_store()
    client = _make_mock_client()
    embedder = _make_mock_embedder()
    _inject_store(store, client, embedder)

    # 预置一条 entry，使 empty 检查通过
    store._entries.append(MemoryEntry.new("dummy"))

    hit1 = _make_hit("记忆内容A", "2025-01-01T10:00:00", 0.95)
    hit2 = _make_hit("记忆内容B", "2025-01-02T11:00:00", 0.80)
    qr = MagicMock()
    qr.points = [hit1, hit2]
    client.query_points.return_value = qr

    results = store.search_with_scores("查询", top_k=2)

    client.query_points.assert_called_once()
    call_kw = client.query_points.call_args.kwargs
    assert call_kw["collection_name"] == "test_collection"
    assert call_kw["limit"] == 2

    assert len(results) == 2
    score0, text0 = results[0]
    assert score0 == 0.95
    assert "记忆内容A" in text0
    assert "2025-01-01" in text0
    print("[OK] test_search_with_scores_calls_query_points")


def test_search_with_scores_empty_store_returns_empty():
    """空 store 的 search_with_scores 应直接返回 []，不调用 Qdrant。"""
    store = _make_store()
    client = _make_mock_client()
    _inject_store(store, client, _make_mock_embedder())

    results = store.search_with_scores("q", top_k=3)

    assert results == []
    client.query_points.assert_not_called()
    print("[OK] test_search_with_scores_empty_store_returns_empty")


# ── recall ────────────────────────────────────────────────────────────────────

def test_recall_returns_formatted_string():
    """recall() 应返回拼接格式化的字符串。"""
    store = _make_store(top_k=3)
    client = _make_mock_client()
    embedder = _make_mock_embedder()
    _inject_store(store, client, embedder)
    store._entries.append(MemoryEntry.new("dummy"))

    hits = [_make_hit("内容X", "2025-06-01T08:00:00", 0.9)]
    qr = MagicMock()
    qr.points = hits
    client.query_points.return_value = qr

    result = store.recall("查询")

    assert "内容X" in result
    assert "2025-06-01" in result
    print("[OK] test_recall_returns_formatted_string")


def test_recall_truncates_output():
    """recall() 应按 max_recall_chars 裁剪输出。"""
    store = _make_store(top_k=1, max_recall_chars=20)
    client = _make_mock_client()
    _inject_store(store, client, _make_mock_embedder())
    store._entries.append(MemoryEntry.new("dummy"))

    long_text = "X" * 200
    hits = [_make_hit(long_text, "2025-01-01T00:00:00", 0.9)]
    qr = MagicMock()
    qr.points = hits
    client.query_points.return_value = qr

    result = store.recall("q")

    assert len(result) <= 20
    print("[OK] test_recall_truncates_output")


def test_recall_empty_store_returns_empty_string():
    """空 store 的 recall 应返回空字符串，不调用 Qdrant。"""
    store = _make_store()
    client = _make_mock_client()
    _inject_store(store, client, _make_mock_embedder())

    assert store.recall("q") == ""
    client.query_points.assert_not_called()
    print("[OK] test_recall_empty_store_returns_empty_string")


# ── save ─────────────────────────────────────────────────────────────────────

def test_save_writes_memories_json():
    """save() 应在 memory_dir 写 memories.json，且 Qdrant 不被调用。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(memory_dir=tmpdir)
        client = _make_mock_client()
        _inject_store(store, client, _make_mock_embedder())

        store._entries.append(MemoryEntry.new("保存测试"))
        store.save()

        json_path = os.path.join(tmpdir, MEMORIES_FILE)
        assert os.path.exists(json_path), "memories.json should exist"
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["text"] == "保存测试"

        client.upsert.assert_not_called()
        print("[OK] test_save_writes_memories_json")


def test_save_empty_store_writes_empty_json():
    """空 store save 后应写出空列表，不崩溃。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(memory_dir=tmpdir)
        _inject_store(store, _make_mock_client(), _make_mock_embedder())

        store.save()

        json_path = os.path.join(tmpdir, MEMORIES_FILE)
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data == []
        print("[OK] test_save_empty_store_writes_empty_json")


# ── rebuild_index ─────────────────────────────────────────────────────────────

def test_rebuild_index_upserts_all_entries():
    """rebuild_index() 应对所有 entries 一次性批量 embed 并 upsert。"""
    store = _make_store()
    client = _make_mock_client(collection_names=["test_collection"])
    embedder = _make_mock_embedder()
    _inject_store(store, client, embedder)

    for i in range(3):
        store._entries.append(MemoryEntry.new(f"entry_{i}"))

    store.rebuild_index()

    embedder.embed_documents.assert_called_once()
    texts_arg = embedder.embed_documents.call_args.args[0]
    assert len(texts_arg) == 3

    client.upsert.assert_called_once()
    points = client.upsert.call_args.kwargs["points"]
    assert len(points) == 3
    print("[OK] test_rebuild_index_upserts_all_entries")


def test_rebuild_index_empty_store_noop():
    """空 store 的 rebuild_index 不应调用 embed 或 upsert。"""
    store = _make_store()
    client = _make_mock_client()
    embedder = _make_mock_embedder()
    _inject_store(store, client, embedder)

    store.rebuild_index()

    embedder.embed_documents.assert_not_called()
    client.upsert.assert_not_called()
    print("[OK] test_rebuild_index_empty_store_noop")


# ── preload ───────────────────────────────────────────────────────────────────

def test_preload_rebuilds_when_counts_differ():
    """点数与 entries 不一致时，preload 应调用 rebuild_index。"""
    store = _make_store()
    client = _make_mock_client(
        collection_names=["test_collection"],
        point_count=0,  # Qdrant 中没有点
    )
    embedder = _make_mock_embedder()
    _inject_store(store, client, embedder)

    # entries 里有 2 条，但 Qdrant 中有 0 条 → 不一致
    store._entries.append(MemoryEntry.new("a"))
    store._entries.append(MemoryEntry.new("b"))

    store.preload()

    # rebuild_index 触发了一次 upsert
    client.upsert.assert_called_once()
    print("[OK] test_preload_rebuilds_when_counts_differ")


def test_preload_skips_rebuild_when_consistent():
    """点数与 entries 一致时，preload 不应调用 upsert。"""
    store = _make_store()
    client = _make_mock_client(
        collection_names=["test_collection"],
        point_count=2,  # 与 entries 长度一致
    )
    embedder = _make_mock_embedder()
    _inject_store(store, client, embedder)

    store._entries.append(MemoryEntry.new("a"))
    store._entries.append(MemoryEntry.new("b"))

    store.preload()

    client.upsert.assert_not_called()
    print("[OK] test_preload_skips_rebuild_when_consistent")


def test_preload_empty_store_noop():
    """空 store preload 只确保集合就绪，不 embed 或 upsert。"""
    store = _make_store()
    client = _make_mock_client(collection_names=["test_collection"], point_count=0)
    embedder = _make_mock_embedder()
    _inject_store(store, client, embedder)

    store.preload()

    client.upsert.assert_not_called()
    embedder.embed_documents.assert_not_called()
    print("[OK] test_preload_empty_store_noop")


# ── recall_timeline（不走 Qdrant）────────────────────────────────────────────

def test_recall_timeline_does_not_use_qdrant():
    """recall_timeline 只读 _entries，不应触碰 Qdrant。"""
    from datetime import datetime, timezone, timedelta

    store = _make_store()
    client = _make_mock_client()
    _inject_store(store, client, _make_mock_embedder())

    base = datetime(2025, 3, 1, tzinfo=timezone.utc)
    for i, text in enumerate(["早", "中", "晚"]):
        ts = (base + timedelta(hours=i)).isoformat()
        store._entries.append(MemoryEntry(id=str(i), text=text, created_at=ts))

    pairs = store.recall_timeline(n=2)

    assert len(pairs) == 2
    assert pairs[0][1] == "中"
    assert pairs[1][1] == "晚"
    client.query_points.assert_not_called()
    print("[OK] test_recall_timeline_does_not_use_qdrant")


# ── 入口 ─────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_ensure_collection_creates_when_missing,
    test_ensure_collection_skips_when_exists,
    test_ensure_collection_idempotent,
    test_add_upserts_to_qdrant,
    test_add_truncates_long_text,
    test_add_returns_memory_entry,
    test_search_with_scores_calls_query_points,
    test_search_with_scores_empty_store_returns_empty,
    test_recall_returns_formatted_string,
    test_recall_truncates_output,
    test_recall_empty_store_returns_empty_string,
    test_save_writes_memories_json,
    test_save_empty_store_writes_empty_json,
    test_rebuild_index_upserts_all_entries,
    test_rebuild_index_empty_store_noop,
    test_preload_rebuilds_when_counts_differ,
    test_preload_skips_rebuild_when_consistent,
    test_preload_empty_store_noop,
    test_recall_timeline_does_not_use_qdrant,
]


if __name__ == "__main__":
    print("=" * 60)
    print("  LongTermStore Qdrant Backend Tests")
    print("=" * 60)
    passed = 0
    failed = 0
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  FAIL  {test_fn.__name__}")
            import traceback
            traceback.print_exc()
    print("=" * 60)
    print(f"  Result: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)
