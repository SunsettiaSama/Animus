from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from config.react.memory.memory_config import LongTermMemoryConfig

MEMORIES_FILE = "memories.json"
FAISS_INDEX_NAME = "memory_index"


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


def _fmt_ts(iso: str) -> str:
    """Convert ISO timestamp to human-readable '[YYYY-MM-DD HH:MM UTC]'."""
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
    """线程安全的长期记忆存储。

    内部持有一把 RLock，保护以下共享状态：
    - _embeddings  （lazy 初始化，防止多线程双重构造）
    - _vectorstore （FAISS index，add / search / save 均需持锁）
    - _entries     （条目列表，add / save 均需持锁）

    典型并发场景：
    - 后台 post_process 线程调用 add() + save()
    - asyncio/stream 线程调用 recall() / search_with_scores()
    RLock 保证两者不交错执行，且同线程内 add() → _get_embeddings() 不死锁。
    """

    def __init__(
        self,
        entries: list[MemoryEntry],
        cfg: LongTermMemoryConfig,
        vectorstore: FAISS | None = None,
    ):
        self._entries = entries
        self._cfg = cfg
        self._vectorstore: FAISS | None = vectorstore
        self._embeddings: HuggingFaceBgeEmbeddings | None = None
        self._lock = threading.RLock()

    # ── Embeddings (lazy, thread-safe) ────────────────────────────────────────

    def _get_embeddings(self) -> HuggingFaceBgeEmbeddings:
        with self._lock:
            if self._embeddings is None:
                import torch

                device = self._cfg.device
                if device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                self._embeddings = HuggingFaceBgeEmbeddings(
                    model_name=self._cfg.model_name_or_path,
                    model_kwargs={"device": device},
                    encode_kwargs={"normalize_embeddings": True},
                    embed_instruction=self._cfg.passage_prefix,
                    query_instruction=self._cfg.query_prefix,
                )
            return self._embeddings

    # ── Index ──────────────────────────────────────────────────────────────────

    def rebuild_index(self) -> None:
        with self._lock:
            if not self._entries:
                self._vectorstore = None
                return
            embeddings = self._get_embeddings()
            docs = [
                Document(
                    page_content=e.text,
                    metadata={"id": e.id, "created_at": e.created_at, **e.meta},
                )
                for e in self._entries
            ]
            self._vectorstore = FAISS.from_documents(docs, embeddings)

    # ── Write ──────────────────────────────────────────────────────────────────

    def add(self, text: str, **meta) -> MemoryEntry:
        text = _trunc(text, self._cfg.max_entry_chars)
        entry = MemoryEntry.new(text, **meta)
        doc = Document(
            page_content=text,
            metadata={"id": entry.id, "created_at": entry.created_at, **meta},
        )
        with self._lock:
            self._entries.append(entry)
            embeddings = self._get_embeddings()
            if self._vectorstore is None:
                self._vectorstore = FAISS.from_documents([doc], embeddings)
            else:
                self._vectorstore.add_documents([doc])
        return entry

    # ── Search ─────────────────────────────────────────────────────────────────

    def search_with_scores(self, query: str, top_k: int) -> list[tuple[float, str]]:
        with self._lock:
            if self._vectorstore is None or not self._entries:
                return []
            results = self._vectorstore.similarity_search_with_relevance_scores(
                query, k=top_k
            )
        return [
            (float(score), f"[{_fmt_ts(doc.metadata.get('created_at', ''))}]\n{doc.page_content}")
            for doc, score in results
        ]

    def recall(self, query: str) -> str:
        with self._lock:
            if self._vectorstore is None or not self._entries:
                return ""
            results = self._vectorstore.similarity_search(query, k=self._cfg.top_k)
        text = "\n\n".join(
            f"[{_fmt_ts(doc.metadata.get('created_at', ''))}]\n{doc.page_content}"
            for doc in results
        )
        return _trunc(text, self._cfg.max_recall_chars)

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self) -> None:
        with self._lock:
            os.makedirs(self._cfg.memory_dir, exist_ok=True)
            json_path = os.path.join(self._cfg.memory_dir, MEMORIES_FILE)
            snapshot = list(self._entries)
            vectorstore = self._vectorstore

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(e) for e in snapshot],
                f,
                ensure_ascii=False,
                indent=2,
            )
        if vectorstore is not None:
            vectorstore.save_local(self._cfg.memory_dir, FAISS_INDEX_NAME)

    # ── Timeline ───────────────────────────────────────────────────────────────

    def recall_timeline(self, n: int = 5) -> list[tuple[str, str]]:
        """Return the n most recent entries as (created_at, text), oldest-first.

        Bypasses FAISS — directly reads the insertion-ordered ``_entries`` list.
        """
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
