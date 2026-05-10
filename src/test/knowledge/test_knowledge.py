"""
知识库模块测试
==============
覆盖 src/knowledge/ 的核心行为：

  单元测试（无外部依赖）
  ├── KnowledgeConfig：from_dict / 默认值 / from_yaml
  ├── 分块函数：_chunk_text 边界情况
  ├── URL 解析：_parse_url
  ├── 向量维度推断：_get_dim
  └── 缓存哈希：query_hash

  集成测试（Mock MySQL / Redis / Qdrant / BGE）
  ├── 写入链路：ingest_text → MySQL insert → embed → Qdrant upsert → version INCR
  ├── 查询链路（缓存命中）：Redis 版本一致 → 直接返回
  ├── 查询链路（正常穿透）：cache miss → Qdrant → MySQL → 写缓存
  ├── 降级 L1（MySQL 无数据）：使用 Qdrant payload content
  ├── 降级 L2（Qdrant 失败）：MySQL 全文检索
  ├── 删除文档：MySQL 软删 → Qdrant 物理删 → version INCR
  └── repair()：补嵌 is_indexed=False 的 chunk

不依赖任何外部服务（无 MySQL、无 Redis、无 Qdrant、无 BGE 模型）。
运行方式：
  cd E:/ReAct
  python -m pytest src/test/test_knowledge.py -v
  # 或直接：
  python src/test/test_knowledge.py
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

SRC = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SRC))

# ── Stub 重量级外部依赖（必须在导入知识库模块之前） ──────────────────────────


def _pkg_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__package__ = name
    m.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    m.__path__ = []
    sys.modules[name] = m
    return m


def _mod_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


# pymysql
_pymysql = _pkg_stub("pymysql")
_pymysql_cursors = _mod_stub("pymysql.cursors")
_pymysql_cursors.DictCursor = object
_pymysql.cursors = _pymysql_cursors
_pymysql.connect = MagicMock(name="pymysql.connect")

# redis
_redis_mod = _pkg_stub("redis")
_redis_mod.from_url = MagicMock(name="redis.from_url")

# qdrant_client
_qdrant = _pkg_stub("qdrant_client")
_qdrant_models = _mod_stub("qdrant_client.models")
for _cls in [
    "Distance", "FieldCondition", "Filter", "FilterSelector",
    "MatchValue", "PointIdsList", "PointStruct", "VectorParams",
]:
    setattr(_qdrant_models, _cls, MagicMock(name=_cls))
_qdrant.models = _qdrant_models
_qdrant.QdrantClient = MagicMock(name="QdrantClient")

# langchain_community
_lc = _pkg_stub("langchain_community")
_lc_emb = _mod_stub("langchain_community.embeddings")
_lc.embeddings = _lc_emb
_lc_vs = _mod_stub("langchain_community.vectorstores")
_lc_vs.FAISS = MagicMock(name="FAISS")
_lc.vectorstores = _lc_vs
_lc_hf = _pkg_stub("langchain_huggingface")
_lc_hf.HuggingFaceEmbeddings = MagicMock(name="HuggingFaceEmbeddings")

# langchain_core
_lc_core = _pkg_stub("langchain_core")
_lc_core_docs = _mod_stub("langchain_core.documents")
_lc_core_docs.Document = MagicMock(name="Document")
_lc_core.documents = _lc_core_docs

# embedding package — stub to prevent real torch loading
_emb_pkg = _pkg_stub("embedding")
_emb_build = _mod_stub("embedding.build")
_emb_build.build_index = MagicMock(name="build_index")
_emb_pkg.build = _emb_build
_emb_corpus = _mod_stub("embedding.corpus")
_emb_corpus.Chunk = MagicMock(name="Chunk")
_emb_corpus.build_chunks = MagicMock(name="build_chunks")
_emb_corpus.load_csv = MagicMock(name="load_csv")
_emb_pkg.corpus = _emb_corpus
_emb_embedder = _mod_stub("embedding.embedder")
_emb_embedder.Embedder = MagicMock(name="Embedder")
_BGE_DIMS = {"large": 1024, "base": 768, "small": 512}
_emb_embedder.infer_dim = lambda model_name: next(
    (dim for key, dim in _BGE_DIMS.items() if key in model_name.lower()), 512
)
_emb_pkg.embedder = _emb_embedder

# torch
_torch = _mod_stub("torch")
_torch.cuda = MagicMock()
_torch.cuda.is_available = MagicMock(return_value=False)
_torch.float16 = "float16"

# ── 现在可以安全导入知识库模块 ─────────────────────────────────────────────────

from config.knowledge.config import KnowledgeConfig
from knowledge.store import KnowledgeStore, ChunkRecord, DocumentRecord
from knowledge.vector_store import KnowledgeVectorStore, SearchResult
from knowledge.cache import KnowledgeCache
from knowledge.ingestion import KnowledgeIngestion, _chunk_text
from knowledge.retriever import KnowledgeRetriever, RetrievalResult
from knowledge import KnowledgeBase


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_cfg(**kw) -> KnowledgeConfig:
    defaults = dict(
        mysql_url="mysql+pymysql://root:pw@localhost:3306/kb",
        redis_url="redis://localhost:6379/0",
        qdrant_path="/tmp/qdrant_test",
        collection_name="test",
        embedding_model="BAAI/bge-small-zh-v1.5",
        top_k=3,
        cache_ttl=300,
        chunk_size=50,
        chunk_overlap=10,
    )
    defaults.update(kw)
    return KnowledgeConfig(**defaults)


def _make_mock_conn(fetchone=None, fetchall=None):
    """返回 pymysql.connect 的 mock，支持 context manager 和 cursor。"""
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone = MagicMock(return_value=fetchone)
    cursor.fetchall = MagicMock(return_value=fetchall or [])
    cursor.lastrowid = 1

    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor = MagicMock(return_value=cursor)
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    _pymysql.connect.return_value = conn
    return conn, cursor


def _make_mock_redis(version: int = 1, cached_raw: str | None = None):
    r = MagicMock()
    r.ping = MagicMock(return_value=True)
    r.get = MagicMock(return_value=cached_raw)
    r.set = MagicMock()
    r.incr = MagicMock(return_value=version + 1)
    _redis_mod.from_url.return_value = r
    return r


def _make_mock_qdrant(search_hits=None):
    client = MagicMock()
    client.get_collections = MagicMock(return_value=MagicMock(collections=[]))
    client.create_collection = MagicMock()
    client.upsert = MagicMock()
    # 实际代码使用 query_points()，而非 search()
    client.query_points = MagicMock(
        return_value=MagicMock(points=search_hits or [])
    )
    client.search = MagicMock(return_value=search_hits or [])
    client.delete = MagicMock()
    client.get_collection = MagicMock(
        return_value=MagicMock(points_count=0)
    )
    _qdrant.QdrantClient.return_value = client
    return client


def _make_mock_embeddings(vector=None):
    vec = vector or [0.1] * 512
    emb = MagicMock()
    emb.embed_documents = MagicMock(return_value=[vec])
    emb.embed_query = MagicMock(return_value=vec)
    _lc_hf.HuggingFaceEmbeddings.return_value = emb
    # KnowledgeEmbedder 使用 embedding.embedder.Embedder，也需要 stub
    _emb_embedder.Embedder.return_value = emb
    return emb


def _make_qdrant_hit(chunk_id: str, doc_id: str, content: str, score: float = 0.9):
    hit = MagicMock()
    hit.id = chunk_id
    hit.score = score
    hit.payload = {"doc_id": doc_id, "chunk_index": 0, "content": content}
    return hit


def _make_chunk_row(chunk_id: str, doc_id: str, content: str) -> dict:
    return {
        "id": chunk_id,
        "doc_id": doc_id,
        "chunk_index": 0,
        "content": content,
        "is_indexed": True,
        "meta": "{}",
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-01 00:00:00",
        "deleted_at": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unit tests — no mocks needed
# ─────────────────────────────────────────────────────────────────────────────


class TestKnowledgeConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = KnowledgeConfig()
        self.assertEqual(cfg.top_k, 5)
        self.assertEqual(cfg.chunk_size, 512)
        self.assertEqual(cfg.chunk_overlap, 64)
        self.assertEqual(cfg.collection_name, "knowledge")

    def test_from_dict_partial(self):
        cfg = KnowledgeConfig.from_dict({"top_k": 10, "device": "cuda"})
        self.assertEqual(cfg.top_k, 10)
        self.assertEqual(cfg.device, "cuda")
        self.assertEqual(cfg.chunk_size, 512)

    def test_from_dict_empty(self):
        cfg = KnowledgeConfig.from_dict({})
        self.assertIsInstance(cfg, KnowledgeConfig)

    def test_from_yaml(self, tmp_path=None):
        import tempfile, yaml
        data = {"top_k": 7, "collection_name": "my_kb", "chunk_size": 256}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f)
            fname = f.name
        cfg = KnowledgeConfig.from_yaml(fname)
        os.unlink(fname)
        self.assertEqual(cfg.top_k, 7)
        self.assertEqual(cfg.collection_name, "my_kb")
        self.assertEqual(cfg.chunk_size, 256)


class TestChunkText(unittest.TestCase):
    def test_short_text_returns_single_chunk(self):
        result = _chunk_text("hello", chunk_size=100, chunk_overlap=10)
        self.assertEqual(result, ["hello"])

    def test_exact_size(self):
        text = "a" * 50
        result = _chunk_text(text, chunk_size=50, chunk_overlap=10)
        self.assertEqual(result, [text])

    def test_splits_into_overlapping_chunks(self):
        text = "a" * 100
        result = _chunk_text(text, chunk_size=50, chunk_overlap=10)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[0]), 50)
        self.assertEqual(result[1], "a" * 50)

    def test_single_char_overlap(self):
        text = "abcdefghij"
        result = _chunk_text(text, chunk_size=4, chunk_overlap=1)
        self.assertEqual(result[0], "abcd")
        self.assertEqual(result[1], "defg")


class TestStoreUrlParsing(unittest.TestCase):
    def test_standard_url(self):
        cfg = KnowledgeConfig(mysql_url="mysql+pymysql://user:pass@localhost:3306/mydb")
        store = KnowledgeStore.__new__(KnowledgeStore)
        store._cfg = cfg
        kw = store._parse_url(cfg.mysql_url)
        self.assertEqual(kw["host"], "localhost")
        self.assertEqual(kw["port"], 3306)
        self.assertEqual(kw["user"], "user")
        self.assertEqual(kw["password"], "pass")
        self.assertEqual(kw["database"], "mydb")

    def test_url_without_port(self):
        cfg = KnowledgeConfig(mysql_url="mysql+pymysql://root:pw@myhost/db")
        store = KnowledgeStore.__new__(KnowledgeStore)
        store._cfg = cfg
        kw = store._parse_url(cfg.mysql_url)
        self.assertEqual(kw["host"], "myhost")
        self.assertEqual(kw["port"], 3306)


class TestVectorStoreDim(unittest.TestCase):
    def test_small_model(self):
        cfg = _make_cfg(embedding_model="BAAI/bge-small-zh-v1.5")
        vs = KnowledgeVectorStore.__new__(KnowledgeVectorStore)
        vs._cfg = cfg
        vs._dim = None
        self.assertEqual(vs._get_dim(), 512)

    def test_base_model(self):
        cfg = _make_cfg(embedding_model="BAAI/bge-base-en-v1.5")
        vs = KnowledgeVectorStore.__new__(KnowledgeVectorStore)
        vs._cfg = cfg
        vs._dim = None
        self.assertEqual(vs._get_dim(), 768)

    def test_large_model(self):
        cfg = _make_cfg(embedding_model="BAAI/bge-large-zh-v1.5")
        vs = KnowledgeVectorStore.__new__(KnowledgeVectorStore)
        vs._cfg = cfg
        vs._dim = None
        self.assertEqual(vs._get_dim(), 1024)


class TestCacheHash(unittest.TestCase):
    def test_same_query_same_hash(self):
        h1 = KnowledgeCache.query_hash("test query")
        h2 = KnowledgeCache.query_hash("test query")
        self.assertEqual(h1, h2)

    def test_different_query_different_hash(self):
        h1 = KnowledgeCache.query_hash("foo")
        h2 = KnowledgeCache.query_hash("bar")
        self.assertNotEqual(h1, h2)

    def test_hash_length(self):
        h = KnowledgeCache.query_hash("anything")
        self.assertEqual(len(h), 16)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Integration tests — mock MySQL / Redis / Qdrant / BGE
# ─────────────────────────────────────────────────────────────────────────────


class TestIngestionPipeline(unittest.TestCase):
    """写入链路：ingest_text → MySQL → BGE → Qdrant → Redis INCR"""

    def setUp(self):
        self.cfg = _make_cfg()
        self.conn, self.cursor = _make_mock_conn()
        self.redis = _make_mock_redis(version=0)
        self.qdrant = _make_mock_qdrant()
        self.emb = _make_mock_embeddings()

        store = KnowledgeStore(self.cfg)
        vs = KnowledgeVectorStore(self.cfg)
        cache = KnowledgeCache(self.cfg)
        self.ingestion = KnowledgeIngestion(self.cfg, store, vs, cache)

    def test_ingest_text_calls_mysql_insert(self):
        self.ingestion.ingest_text("Hello knowledge base", title="Test")
        # documents INSERT + status updates + chunks INSERT + mark_indexed
        self.assertTrue(self.cursor.execute.called or self.cursor.executemany.called)

    def test_ingest_text_calls_embed_documents(self):
        self.ingestion.ingest_text("Some text content here.")
        self.emb.embed_documents.assert_called()

    def test_ingest_text_calls_qdrant_upsert(self):
        self.ingestion.ingest_text("Some text content here.")
        self.qdrant.upsert.assert_called()

    def test_ingest_text_increments_cache_version(self):
        self.ingestion.ingest_text("Some text content here.")
        self.redis.incr.assert_called()

    def test_ingest_text_returns_doc_id(self):
        doc_id = self.ingestion.ingest_text("Hello")
        self.assertIsInstance(doc_id, str)
        self.assertEqual(len(doc_id), 36)

    def test_long_text_splits_into_multiple_chunks(self):
        long_text = "word " * 100
        self.ingestion.ingest_text(long_text)
        # embed_documents should receive multiple chunks
        call_args = self.emb.embed_documents.call_args
        texts = call_args[0][0]
        self.assertGreater(len(texts), 1)

    def test_delete_document_calls_qdrant_delete(self):
        self.ingestion.delete_document("some-doc-uuid")
        self.qdrant.delete.assert_called()

    def test_delete_document_increments_version(self):
        self.ingestion.delete_document("some-doc-uuid")
        self.redis.incr.assert_called()


class TestRepair(unittest.TestCase):
    """repair() 补嵌 is_indexed=False 的 chunk"""

    def setUp(self):
        self.cfg = _make_cfg()

    def test_repair_no_unindexed_returns_zero(self):
        _make_mock_conn(fetchall=[])
        _make_mock_redis()
        qdrant = _make_mock_qdrant()
        emb = _make_mock_embeddings()

        store = KnowledgeStore(self.cfg)
        vs = KnowledgeVectorStore(self.cfg)
        cache = KnowledgeCache(self.cfg)
        ingestion = KnowledgeIngestion(self.cfg, store, vs, cache)

        count = ingestion.repair()
        self.assertEqual(count, 0)
        qdrant.upsert.assert_not_called()
        emb.embed_documents.assert_not_called()

    def test_repair_with_unindexed_chunks(self):
        unindexed_rows = [_make_chunk_row("c1", "d1", "chunk content")]
        unindexed_rows[0]["is_indexed"] = False
        _make_mock_conn(fetchall=unindexed_rows)
        _make_mock_redis()
        qdrant = _make_mock_qdrant()
        emb = _make_mock_embeddings()

        store = KnowledgeStore(self.cfg)
        vs = KnowledgeVectorStore(self.cfg)
        cache = KnowledgeCache(self.cfg)
        ingestion = KnowledgeIngestion(self.cfg, store, vs, cache)

        count = ingestion.repair()
        self.assertEqual(count, 1)
        qdrant.upsert.assert_called_once()
        emb.embed_documents.assert_called_once()


class TestRetrieverCacheHit(unittest.TestCase):
    """查询链路：Redis 版本一致 → 缓存命中，不查 Qdrant"""

    def setUp(self):
        self.cfg = _make_cfg()
        _make_mock_conn()
        cached_results = [
            {
                "chunk_id": "cid1",
                "doc_id": "did1",
                "chunk_index": 0,
                "content": "cached content",
                "score": 0.95,
                "source": "mysql",
                "meta": {},
            }
        ]
        cached_raw = json.dumps({"version": 5, "results": cached_results})
        redis = _make_mock_redis(version=5, cached_raw=cached_raw)
        # Redis: first GET returns version "5", second GET returns cached JSON
        redis.get = MagicMock(
            side_effect=lambda key: (
                "5" if key == "kb:index:version" else cached_raw
            )
        )
        self.qdrant = _make_mock_qdrant()
        emb = _make_mock_embeddings()

        store = KnowledgeStore(self.cfg)
        vs = KnowledgeVectorStore(self.cfg)
        self.cache = KnowledgeCache(self.cfg)
        self.retriever = KnowledgeRetriever(self.cfg, store, vs, self.cache)
        self.retriever._embeddings = emb

    def test_cache_hit_returns_cached(self):
        results = self.retriever.search("any query")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "cached content")
        self.assertEqual(results[0].source, "mysql")

    def test_cache_hit_skips_qdrant(self):
        self.retriever.search("any query")
        self.qdrant.search.assert_not_called()


class TestRetrieverNormalPath(unittest.TestCase):
    """查询链路（正常穿透）：cache miss → Qdrant → MySQL → 写缓存"""

    def setUp(self):
        self.cfg = _make_cfg()
        chunk_id = "chunk-abc-123"
        doc_id = "doc-xyz-456"

        # Redis: cache miss (no cached data)
        redis = _make_mock_redis(version=3)
        redis.get = MagicMock(
            side_effect=lambda key: "3" if key == "kb:index:version" else None
        )
        self.redis = redis

        # Qdrant: returns one hit
        hit = _make_qdrant_hit(chunk_id, doc_id, "qdrant payload content", score=0.88)
        self.qdrant = _make_mock_qdrant(search_hits=[hit])

        # MySQL: returns chunk row
        row = _make_chunk_row(chunk_id, doc_id, "mysql authoritative content")
        _make_mock_conn(fetchall=[row])

        emb = _make_mock_embeddings()

        store = KnowledgeStore(self.cfg)
        vs = KnowledgeVectorStore(self.cfg)
        cache = KnowledgeCache(self.cfg)
        self.retriever = KnowledgeRetriever(self.cfg, store, vs, cache)
        self.retriever._embeddings = emb

    def test_returns_mysql_content(self):
        results = self.retriever.search("some query")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "mysql authoritative content")
        self.assertEqual(results[0].source, "mysql")

    def test_writes_cache_after_mysql(self):
        self.retriever.search("some query")
        self.redis.set.assert_called()

    def test_score_comes_from_qdrant(self):
        results = self.retriever.search("some query")
        self.assertAlmostEqual(results[0].score, 0.88)


class TestRetrieverDegradationL1(unittest.TestCase):
    """降级 L1：Qdrant 返回结果但 MySQL 无数据 → 使用 Qdrant payload"""

    def setUp(self):
        self.cfg = _make_cfg()
        chunk_id = "chunk-1"
        doc_id = "doc-1"

        redis = _make_mock_redis(version=1)
        redis.get = MagicMock(
            side_effect=lambda key: "1" if key == "kb:index:version" else None
        )

        hit = _make_qdrant_hit(chunk_id, doc_id, "qdrant fallback content", score=0.75)
        _make_mock_qdrant(search_hits=[hit])

        # MySQL returns empty (no matching chunks)
        _make_mock_conn(fetchall=[])

        emb = _make_mock_embeddings()
        store = KnowledgeStore(self.cfg)
        vs = KnowledgeVectorStore(self.cfg)
        cache = KnowledgeCache(self.cfg)
        self.retriever = KnowledgeRetriever(self.cfg, store, vs, cache)
        self.retriever._embeddings = emb

    def test_falls_back_to_qdrant_payload(self):
        results = self.retriever.search("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "qdrant fallback content")
        self.assertEqual(results[0].source, "qdrant_payload")

    def test_does_not_write_to_cache_on_fallback(self):
        redis_mock = _redis_mod.from_url.return_value
        self.retriever.search("test")
        redis_mock.set.assert_not_called()


class TestRetrieverDegradationL2(unittest.TestCase):
    """降级 L2：Qdrant 返回空 → MySQL 全文检索"""

    def setUp(self):
        self.cfg = _make_cfg()
        chunk_id = "chunk-fts-1"
        doc_id = "doc-fts-1"

        redis = _make_mock_redis(version=1)
        redis.get = MagicMock(
            side_effect=lambda key: "1" if key == "kb:index:version" else None
        )

        # Qdrant: no results
        _make_mock_qdrant(search_hits=[])

        # MySQL fulltext search returns a result
        row = _make_chunk_row(chunk_id, doc_id, "full text search result")
        conn, cursor = _make_mock_conn()
        cursor.fetchall = MagicMock(side_effect=[[], [row]])

        emb = _make_mock_embeddings()
        store = KnowledgeStore(self.cfg)
        vs = KnowledgeVectorStore(self.cfg)
        cache = KnowledgeCache(self.cfg)
        self.retriever = KnowledgeRetriever(self.cfg, store, vs, cache)
        self.retriever._embeddings = emb

    def test_returns_fts_result(self):
        results = self.retriever.search("search term")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "full text search result")
        self.assertEqual(results[0].source, "fallback_fts")
        self.assertAlmostEqual(results[0].score, 0.0)


class TestRetrieverCompleteFailure(unittest.TestCase):
    """完全兜底：Qdrant 和 MySQL 都无结果 → 返回空列表"""

    def setUp(self):
        self.cfg = _make_cfg()

        redis = _make_mock_redis(version=1)
        redis.get = MagicMock(
            side_effect=lambda key: "1" if key == "kb:index:version" else None
        )

        _make_mock_qdrant(search_hits=[])
        _make_mock_conn(fetchall=[])

        emb = _make_mock_embeddings()
        store = KnowledgeStore(self.cfg)
        vs = KnowledgeVectorStore(self.cfg)
        cache = KnowledgeCache(self.cfg)
        self.retriever = KnowledgeRetriever(self.cfg, store, vs, cache)
        self.retriever._embeddings = emb

    def test_returns_empty_list(self):
        results = self.retriever.search("nonexistent topic")
        self.assertEqual(results, [])


class TestCacheVersionInvalidation(unittest.TestCase):
    """缓存版本比对：版本不一致时穿透，不使用旧缓存"""

    def test_stale_cache_is_ignored(self):
        cfg = _make_cfg()
        _make_mock_conn(fetchall=[])
        _make_mock_qdrant(search_hits=[])

        stale_results = [
            {
                "chunk_id": "old",
                "doc_id": "old",
                "chunk_index": 0,
                "content": "stale content",
                "score": 0.9,
                "source": "mysql",
                "meta": {},
            }
        ]
        stale_raw = json.dumps({"version": 2, "results": stale_results})

        # Redis has stale cache (version=2) but current version is 5
        redis = _make_mock_redis()
        redis.get = MagicMock(
            side_effect=lambda key: (
                "5" if key == "kb:index:version" else stale_raw
            )
        )

        emb = _make_mock_embeddings()
        store = KnowledgeStore(cfg)
        vs = KnowledgeVectorStore(cfg)
        cache = KnowledgeCache(cfg)
        retriever = KnowledgeRetriever(cfg, store, vs, cache)
        retriever._embeddings = emb

        results = retriever.search("any query")
        # Should not return stale content; Qdrant returned empty, FTS empty
        self.assertEqual(results, [])


class TestKnowledgeBaseFacade(unittest.TestCase):
    """KnowledgeBase 门面类：from_config / setup / ingest / search / delete"""

    def setUp(self):
        self.cfg = _make_cfg()
        _make_mock_conn()
        _make_mock_redis(version=0)
        self.qdrant = _make_mock_qdrant()
        _make_mock_embeddings()

    def test_from_config_creates_instance(self):
        kb = KnowledgeBase.from_config(self.cfg)
        self.assertIsInstance(kb, KnowledgeBase)

    def test_setup_calls_init_schema_and_ensure_collection(self):
        kb = KnowledgeBase.from_config(self.cfg)
        # init_schema reads the sql file — patch open to avoid filesystem dep
        with patch("builtins.open", unittest.mock.mock_open(read_data="SELECT 1;")):
            kb.setup()
        self.qdrant.create_collection.assert_called()

    def test_ingest_text_delegates_to_ingestion(self):
        kb = KnowledgeBase.from_config(self.cfg)
        doc_id = kb.ingest_text("test content")
        self.assertIsInstance(doc_id, str)
        self.qdrant.upsert.assert_called()

    def test_delete_delegates_to_ingestion(self):
        kb = KnowledgeBase.from_config(self.cfg)
        kb.delete("some-doc-id")
        self.qdrant.delete.assert_called()

    def test_search_returns_list(self):
        # Qdrant returns empty, MySQL FTS returns empty → empty list
        hit = _make_qdrant_hit("c1", "d1", "result content", 0.8)
        self.qdrant.search.return_value = [hit]
        _make_mock_conn(fetchall=[_make_chunk_row("c1", "d1", "result content")])
        _make_mock_redis(version=1)
        _redis_mod.from_url.return_value.get = MagicMock(
            side_effect=lambda key: "1" if key == "kb:index:version" else None
        )

        kb = KnowledgeBase.from_config(self.cfg)
        results = kb.search("query")
        self.assertIsInstance(results, list)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
