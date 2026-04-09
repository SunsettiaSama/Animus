from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import faiss
import numpy as np
import torch
from FlagEmbedding import FlagModel

from config.react.memory.memory_config import LongTermMemoryConfig

MEMORIES_FILE = "memories.json"
INDEX_FILE = "memory_index.faiss"


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
        index: faiss.IndexFlatIP | None = None,
    ):
        self._entries = entries
        self._cfg = cfg
        self._index: faiss.IndexFlatIP | None = index
        self._model: FlagModel | None = None

    # --- model (lazy) ---

    def _get_model(self) -> FlagModel:
        if self._model is None:
            device = self._cfg.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = FlagModel(
                self._cfg.model_name_or_path,
                use_fp16=self._cfg.use_fp16,
                device=device,
            )
        return self._model

    # --- index ---

    def rebuild_index(self) -> None:
        if not self._entries:
            self._index = None
            return
        model = self._get_model()
        texts = [self._cfg.passage_prefix + e.text for e in self._entries]
        vecs = np.array(model.encode(texts), dtype="float32")
        faiss.normalize_L2(vecs)
        idx = faiss.IndexFlatIP(vecs.shape[1])
        idx.add(vecs)
        self._index = idx

    # --- search ---

    def search_with_scores(self, query: str, top_k: int) -> list[tuple[float, str]]:
        if self._index is None or not self._entries:
            return []
        model = self._get_model()
        vec = np.array(
            model.encode(self._cfg.query_prefix + query),
            dtype="float32",
        )[np.newaxis, :]
        faiss.normalize_L2(vec)
        scores, indices = self._index.search(vec, top_k)
        return [
            (float(scores[0][i]), self._entries[indices[0][i]].text)
            for i in range(len(indices[0]))
            if indices[0][i] != -1
        ]

    def recall(self, query: str) -> str:
        if self._index is None or not self._entries:
            return ""
        model = self._get_model()
        vec = np.array(
            model.encode(self._cfg.query_prefix + query),
            dtype="float32",
        )[np.newaxis, :]
        faiss.normalize_L2(vec)
        scores, indices = self._index.search(vec, self._cfg.top_k)
        results = [
            self._entries[i].text
            for _, i in zip(scores[0], indices[0])
            if i != -1
        ]
        return "\n\n".join(results)

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
        if self._index is not None:
            faiss.write_index(
                self._index,
                os.path.join(self._cfg.memory_dir, INDEX_FILE),
            )

    # --- entries ---

    @property
    def entries(self) -> list[MemoryEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
