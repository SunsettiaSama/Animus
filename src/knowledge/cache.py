from __future__ import annotations

import hashlib
import json
import random

import redis

from config.knowledge.config import KnowledgeConfig


def _jitter(base: int, pct: float = 0.2) -> int:
    """Return base TTL ± up to pct fraction, minimum 1 second."""
    delta = int(base * pct)
    return max(1, base + random.randint(-delta, delta))

_KEY_VERSION = "kb:index:version"
_KEY_DOMAIN_VERSION = "kb:domain:{}:version"
_KEY_QUERY = "kb:q:{}"
_KEY_CHUNK = "kb:chunk:{}"
_KEY_DOC_STATUS = "kb:doc:{}:status"


class KnowledgeCache:
    def __init__(self, cfg: KnowledgeConfig):
        self._ttl = cfg.cache_ttl
        self._r: redis.Redis = redis.from_url(cfg.redis_url, decode_responses=True)

    def ping(self) -> bool:
        return bool(self._r.ping())

    # ── Version ───────────────────────────────────────────────────────────────

    def get_version(self, domain: str | None = None) -> int:
        global_v = int(self._r.get(_KEY_VERSION) or 0)
        if domain is None:
            return global_v
        domain_v = int(self._r.get(_KEY_DOMAIN_VERSION.format(domain)) or 0)
        return max(global_v, domain_v)

    def incr_version(self, domain: str | None = None) -> int:
        if domain is not None:
            return int(self._r.incr(_KEY_DOMAIN_VERSION.format(domain)))
        return int(self._r.incr(_KEY_VERSION))

    # ── Query cache ───────────────────────────────────────────────────────────

    @staticmethod
    def query_hash(query: str, mode: str = "semantic", top_k: int = 5) -> str:
        return hashlib.sha256(f"{mode}:{top_k}:{query}".encode()).hexdigest()[:16]

    def get_query(
        self,
        query: str,
        mode: str = "semantic",
        top_k: int = 5,
        domain: str | None = None,
    ) -> list[dict] | None:
        raw = self._r.get(_KEY_QUERY.format(self.query_hash(query, mode, top_k)))
        if raw is None:
            return None
        cached = json.loads(raw)
        if cached.get("version") != self.get_version(domain):
            return None
        return cached.get("results")

    def set_query(
        self,
        query: str,
        results: list[dict],
        mode: str = "semantic",
        top_k: int = 5,
        domain: str | None = None,
    ) -> None:
        version = self.get_version(domain)
        payload = json.dumps({"version": version, "results": results})
        self._r.set(
            _KEY_QUERY.format(self.query_hash(query, mode, top_k)),
            payload,
            ex=_jitter(self._ttl),
        )

    # ── Chunk cache ───────────────────────────────────────────────────────────

    def get_chunk(self, chunk_id: str) -> str | None:
        return self._r.get(_KEY_CHUNK.format(chunk_id))

    def set_chunk(self, chunk_id: str, content: str, ttl: int = 600) -> None:
        self._r.set(_KEY_CHUNK.format(chunk_id), content, ex=_jitter(ttl))

    # ── Doc status ────────────────────────────────────────────────────────────

    def set_doc_status(self, doc_id: str, status: str) -> None:
        self._r.set(_KEY_DOC_STATUS.format(doc_id), status, ex=_jitter(60))

    def get_doc_status(self, doc_id: str) -> str | None:
        return self._r.get(_KEY_DOC_STATUS.format(doc_id))
