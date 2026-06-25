from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from copy import deepcopy
from typing import Any


class JsonCollection:
    """Small local JSON collection keyed by row id.

    The collection is process-safe through an in-process lock and writes through
    a temporary file followed by ``os.replace``. It intentionally does not try
    to emulate SQL semantics.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()

    @property
    def path(self) -> str:
        return self._path

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(row) for row in self._read().values()]

    def get(self, key: str) -> dict[str, Any] | None:
        kid = key.strip()
        if not kid:
            return None
        with self._lock:
            row = self._read().get(kid)
            return deepcopy(row) if row is not None else None

    def upsert(self, key: str, row: dict[str, Any]) -> None:
        kid = key.strip()
        if not kid:
            raise ValueError("json collection key cannot be empty")
        with self._lock:
            data = self._read()
            data[kid] = deepcopy(row)
            self._write(data)

    def delete(self, key: str) -> None:
        kid = key.strip()
        if not kid:
            return
        with self._lock:
            data = self._read()
            data.pop(kid, None)
            self._write(data)

    def update(self, key: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        kid = key.strip()
        if not kid:
            raise ValueError("json collection key cannot be empty")
        with self._lock:
            data = self._read()
            current = deepcopy(data.get(kid) or {})
            updated = fn(current)
            data[kid] = deepcopy(updated)
            self._write(data)
            return deepcopy(updated)

    def filter(self, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(row) for row in self._read().values() if predicate(row)]

    def _read(self) -> dict[str, dict[str, Any]]:
        if not os.path.exists(self._path):
            return {}
        with open(self._path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"JSON collection must be an object: {self._path}")
        return {str(k): dict(v) for k, v in raw.items()}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, self._path)


class JsonStorageService:
    """Factory for named JSON collections rooted at one directory."""

    def __init__(self, root: str) -> None:
        self._root = root
        self._collections: dict[str, JsonCollection] = {}
        self._lock = threading.Lock()

    @property
    def root(self) -> str:
        return self._root

    def collection(self, name: str) -> JsonCollection:
        normalized = name.strip().replace("\\", "/").strip("/")
        if not normalized:
            raise ValueError("collection name cannot be empty")
        with self._lock:
            existing = self._collections.get(normalized)
            if existing is not None:
                return existing
            path = os.path.join(self._root, *normalized.split("/")) + ".json"
            collection = JsonCollection(path)
            self._collections[normalized] = collection
            return collection
