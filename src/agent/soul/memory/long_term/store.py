from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

# ── Shared QdrantClient registry ──────────────────────────────────────────────
# QdrantLocal (file-based) acquires a portalocker file lock on __init__ and
# holds it for its entire lifetime.  Only ONE QdrantClient per path may exist
# at a time.  We keep a module-level registry so that multiple LongTermStore
# instances that share the same qdrant_path (e.g. the WebUI session and a bot
# AgentSession) reuse the same client rather than each trying to acquire the
# lock independently, which raises "already accessed by another instance".

_CLIENT_REGISTRY: dict[str, QdrantClient] = {}
_CLIENT_REGISTRY_LOCK = threading.Lock()


def _get_or_create_client(path: str) -> QdrantClient:
    with _CLIENT_REGISTRY_LOCK:
        if path not in _CLIENT_REGISTRY:
            os.makedirs(path, exist_ok=True)
            _CLIENT_REGISTRY[path] = QdrantClient(path=path)
        return _CLIENT_REGISTRY[path]

from config.agent.memory.memory_config import LongTermMemoryConfig
from embedding.embedder import Embedder, infer_dim

MEMORIES_FILE = "memories.json"


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


def _fmt_ts(iso: str) -> str:
    return iso[:16].replace("T", " ") + " UTC"


@dataclass
class MemoryEntry:
    id: str
    text: str
    created_at: str
    meta: dict = field(default_factory=dict)

    @staticmethod
    def new(text: str, **meta) -> MemoryEntry:
        return MemoryEntry(
            id=str(uuid.uuid4()),
            text=text,
            created_at=datetime.now(timezone.utc).isoformat(),
            meta=meta,
        )


class LongTermStore:
    """线程安全的长期记忆存储，向量后端为 Qdrant（本地嵌入式）。

    懒加载设计：init 阶段仅记录配置，不加载嵌入模型；首次 add/search 时
    才真正初始化 Embedder 和 QdrantClient。

    _entries 列表维护插入顺序，用于时间线回溯（recall_timeline）；
    Qdrant 集合负责语义向量检索，自动持久化到 cfg.qdrant_path。
    """

    def __init__(
        self,
        entries: list[MemoryEntry],
        cfg: LongTermMemoryConfig,
    ):
        self._entries = entries
        self._cfg = cfg
        self._embedder: Embedder | None = None
        self._collection_ready = False
        self._lock = threading.RLock()

    # ── Lazy init ─────────────────────────────────────────────────────────────

    def _get_embedder(self) -> Embedder:
        with self._lock:
            if self._embedder is None:
                self._embedder = Embedder(
                    model_name=self._cfg.model_name_or_path,
                    device=self._cfg.device,
                    use_fp16=self._cfg.use_fp16,
                    batch_size=32,
                    query_prefix=self._cfg.query_prefix,
                    passage_prefix=self._cfg.passage_prefix,
                )
        return self._embedder

    def _get_client(self) -> QdrantClient:
        return _get_or_create_client(self._cfg.qdrant_path)

    def _ensure_collection(self) -> None:
        client = self._get_client()
        with self._lock:
            if self._collection_ready:
                return
            dim = infer_dim(self._cfg.model_name_or_path)
            existing = {c.name for c in client.get_collections().collections}
            if self._cfg.collection_name in existing:
                info = client.get_collection(self._cfg.collection_name)
                stored_dim = info.config.params.vectors.size
                if stored_dim != dim:
                    # Dimension mismatch — model changed; drop stale collection.
                    client.delete_collection(self._cfg.collection_name)
                    existing.discard(self._cfg.collection_name)
            if self._cfg.collection_name not in existing:
                client.create_collection(
                    collection_name=self._cfg.collection_name,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
            self._collection_ready = True

    # ── Preload ───────────────────────────────────────────────────────────────

    def preload(self) -> None:
        """后台预热：初始化 Embedder（加载模型权重）和 Qdrant，检测数据一致性并在必要时重建。"""
        self._ensure_collection()
        # Always warm up the embedding model regardless of whether entries exist,
        # so the first user message doesn't pay the model-load cost.
        self._get_embedder().warm_up()
        client = self._get_client()
        with self._lock:
            if not self._entries:
                return
            info = client.get_collection(self._cfg.collection_name)
            stored = info.points_count or 0
        if stored != len(self._entries):
            self.rebuild_index()

    # ── Index ─────────────────────────────────────────────────────────────────

    def rebuild_index(self) -> None:
        """将 _entries 全量重新写入 Qdrant 集合。"""
        with self._lock:
            entries = list(self._entries)
        if not entries:
            return
        self._ensure_collection()
        embedder = self._get_embedder()
        client = self._get_client()
        texts = [e.text for e in entries]
        vectors = embedder.embed_documents(texts)
        points = [
            PointStruct(
                id=e.id,
                vector=vec,
                payload={"text": e.text, "created_at": e.created_at, **e.meta},
            )
            for e, vec in zip(entries, vectors)
        ]
        client.upsert(collection_name=self._cfg.collection_name, points=points)

    # ── Write ──────────────────────────────────────────────────────────────────

    def add(self, text: str, **meta) -> MemoryEntry:
        text = _trunc(text, self._cfg.max_entry_chars)
        entry = MemoryEntry.new(text, **meta)
        self._ensure_collection()
        embedder = self._get_embedder()
        vector = embedder.embed_documents([text])[0]
        point = PointStruct(
            id=entry.id,
            vector=vector,
            payload={"text": text, "created_at": entry.created_at, **meta},
        )
        with self._lock:
            self._entries.append(entry)
            self._get_client().upsert(
                collection_name=self._cfg.collection_name, points=[point]
            )
        return entry

    # ── Search ─────────────────────────────────────────────────────────────────

    def search_with_scores(self, query: str, top_k: int) -> list[tuple[float, str]]:
        with self._lock:
            if not self._entries:
                return []
        self._ensure_collection()
        vector = self._get_embedder().embed_query(query)
        hits = self._get_client().query_points(
            collection_name=self._cfg.collection_name,
            query=vector,
            limit=top_k,
            with_payload=True,
        ).points
        return [
            (
                float(hit.score),
                f"[{_fmt_ts((hit.payload or {}).get('created_at', ''))}]\n"
                f"{(hit.payload or {}).get('text', '')}",
            )
            for hit in hits
        ]

    def recall(self, query: str) -> str:
        with self._lock:
            if not self._entries:
                return ""
        self._ensure_collection()
        vector = self._get_embedder().embed_query(query)
        hits = self._get_client().query_points(
            collection_name=self._cfg.collection_name,
            query=vector,
            limit=self._cfg.top_k,
            with_payload=True,
        ).points
        text = "\n\n".join(
            f"[{_fmt_ts((hit.payload or {}).get('created_at', ''))}]\n"
            f"{(hit.payload or {}).get('text', '')}"
            for hit in hits
        )
        return _trunc(text, self._cfg.max_recall_chars)

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self) -> None:
        with self._lock:
            os.makedirs(self._cfg.memory_dir, exist_ok=True)
            json_path = os.path.join(self._cfg.memory_dir, MEMORIES_FILE)
            snapshot = list(self._entries)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(e) for e in snapshot],
                f,
                ensure_ascii=False,
                indent=2,
            )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        # The QdrantClient is shared via the module-level registry and must not
        # be closed here — other LongTermStore instances may still be using it.
        # Just reset this instance's collection-ready flag so the next access
        # re-validates the collection state.
        with self._lock:
            self._collection_ready = False

    # ── Timeline ───────────────────────────────────────────────────────────────

    def recall_timeline(self, n: int = 5) -> list[tuple[str, str]]:
        with self._lock:
            recent = list(self._entries[-n:]) if n > 0 else list(self._entries)
        return [(e.created_at, e.text) for e in recent]

    # ── Entries ────────────────────────────────────────────────────────────────

    @property
    def entries(self) -> list[MemoryEntry]:
        with self._lock:
            return list(self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
