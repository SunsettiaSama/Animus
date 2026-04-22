from __future__ import annotations

import json
import os
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

    # --- embeddings (lazy) ---

    def _get_embeddings(self) -> HuggingFaceBgeEmbeddings:
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

    # --- index ---

    def rebuild_index(self) -> None:
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

    # --- write ---

    def add(self, text: str, **meta) -> MemoryEntry:
        text = _trunc(text, self._cfg.max_entry_chars)
        entry = MemoryEntry.new(text, **meta)
        self._entries.append(entry)
        doc = Document(
            page_content=text,
            metadata={"id": entry.id, "created_at": entry.created_at, **meta},
        )
        embeddings = self._get_embeddings()
        if self._vectorstore is None:
            self._vectorstore = FAISS.from_documents([doc], embeddings)
        else:
            self._vectorstore.add_documents([doc])
        return entry

    # --- search ---

    def search_with_scores(self, query: str, top_k: int) -> list[tuple[float, str]]:
        if self._vectorstore is None or not self._entries:
            return []
        results = self._vectorstore.similarity_search_with_relevance_scores(query, k=top_k)
        return [(float(score), doc.page_content) for doc, score in results]

    def recall(self, query: str) -> str:
        if self._vectorstore is None or not self._entries:
            return ""
        results = self._vectorstore.similarity_search(query, k=self._cfg.top_k)
        text = "\n\n".join(doc.page_content for doc in results)
        return _trunc(text, self._cfg.max_recall_chars)

    # --- persistence ---

    def save(self) -> None:
        os.makedirs(self._cfg.memory_dir, exist_ok=True)
        json_path = os.path.join(self._cfg.memory_dir, MEMORIES_FILE)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(e) for e in self._entries],
                f,
                ensure_ascii=False,
                indent=2,
            )
        if self._vectorstore is not None:
            self._vectorstore.save_local(self._cfg.memory_dir, FAISS_INDEX_NAME)

    # --- entries ---

    @property
    def entries(self) -> list[MemoryEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
