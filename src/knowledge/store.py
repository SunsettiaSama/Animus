from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator

import pymysql
import pymysql.cursors

from config.knowledge.config import KnowledgeConfig


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class DocumentRecord:
    id: str
    source: str
    source_type: str
    title: str
    status: str
    meta: dict
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass
class ChunkRecord:
    id: str
    doc_id: str
    chunk_index: int
    content: str
    is_indexed: bool
    meta: dict
    created_at: str
    updated_at: str
    deleted_at: str | None


class KnowledgeStore:
    def __init__(self, cfg: KnowledgeConfig):
        self._cfg = cfg
        self._conn_kwargs = self._parse_url(cfg.mysql_url)

    def _parse_url(self, url: str) -> dict:
        url = url.replace("mysql+pymysql://", "")
        user_pass, rest = url.split("@", 1)
        user, password = user_pass.split(":", 1)
        host_port, db = rest.split("/", 1)
        host, port = (host_port.rsplit(":", 1) if ":" in host_port else (host_port, "3306"))
        return {
            "host": host,
            "port": int(port),
            "user": user,
            "password": password,
            "database": db,
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
        }

    @contextmanager
    def _conn(self) -> Generator[pymysql.connections.Connection, None, None]:
        conn = pymysql.connect(**self._conn_kwargs)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, encoding="utf-8") as f:
            sql = f.read()
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with self._conn() as conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)

    # ── Documents ─────────────────────────────────────────────────────────────

    def insert_document(
        self,
        source: str,
        source_type: str,
        title: str = "",
        meta: dict | None = None,
    ) -> str:
        doc_id = _new_id()
        now = _now()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (id, source, source_type, title, status, meta, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s)
                    """,
                    (doc_id, source, source_type, title, json.dumps(meta or {}), now, now),
                )
        return doc_id

    def update_document_status(self, doc_id: str, status: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET status=%s, updated_at=%s WHERE id=%s",
                    (status, _now(), doc_id),
                )

    def delete_document(self, doc_id: str) -> None:
        now = _now()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET deleted_at=%s, updated_at=%s WHERE id=%s",
                    (now, now, doc_id),
                )
                cur.execute(
                    "UPDATE content_blobs SET deleted_at=%s, updated_at=%s WHERE doc_id=%s",
                    (now, now, doc_id),
                )
                cur.execute(
                    "UPDATE doc_chunks SET deleted_at=%s, updated_at=%s WHERE doc_id=%s",
                    (now, now, doc_id),
                )

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM documents WHERE id=%s", (doc_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_doc(row)

    def list_documents(self, include_deleted: bool = False) -> list[DocumentRecord]:
        sql = "SELECT * FROM documents"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY created_at DESC"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        return [self._row_to_doc(r) for r in rows]

    def _row_to_doc(self, row: dict) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            source=row["source"],
            source_type=row["source_type"],
            title=row["title"] or "",
            status=row["status"],
            meta=json.loads(row["meta"]) if row["meta"] else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            deleted_at=str(row["deleted_at"]) if row["deleted_at"] else None,
        )

    # ── Content Blobs ─────────────────────────────────────────────────────────

    def insert_blob(self, doc_id: str, content: str, encoding: str = "utf-8") -> str:
        blob_id = _new_id()
        now = _now()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO content_blobs (id, doc_id, content, encoding, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (blob_id, doc_id, content, encoding, now, now),
                )
        return blob_id

    def get_blob(self, doc_id: str) -> str | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content FROM content_blobs WHERE doc_id=%s AND deleted_at IS NULL",
                    (doc_id,),
                )
                row = cur.fetchone()
        return row["content"] if row else None

    # ── Chunks ────────────────────────────────────────────────────────────────

    def insert_chunks(
        self, doc_id: str, chunks: list[tuple[int, str, dict]]
    ) -> list[str]:
        """Insert multiple chunks. chunks = [(chunk_index, content, meta), ...]"""
        now = _now()
        ids = [_new_id() for _ in chunks]
        rows = [
            (cid, doc_id, idx, text, json.dumps(meta), now, now)
            for cid, (idx, text, meta) in zip(ids, chunks)
        ]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO doc_chunks (id, doc_id, chunk_index, content, meta, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
        return ids

    def mark_chunks_indexed(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join(["%s"] * len(chunk_ids))
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE doc_chunks SET is_indexed=TRUE, updated_at=%s WHERE id IN ({placeholders})",
                    [_now()] + chunk_ids,
                )

    def get_unindexed_chunks(self) -> list[ChunkRecord]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM doc_chunks WHERE is_indexed=FALSE AND deleted_at IS NULL"
                )
                rows = cur.fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def get_all_active_chunks(self) -> list[ChunkRecord]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM doc_chunks WHERE deleted_at IS NULL ORDER BY doc_id, chunk_index"
                )
                rows = cur.fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[ChunkRecord]:
        if not chunk_ids:
            return []
        placeholders = ",".join(["%s"] * len(chunk_ids))
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM doc_chunks WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                    chunk_ids,
                )
                rows = cur.fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def get_chunks_by_doc(self, doc_id: str) -> list[ChunkRecord]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM doc_chunks WHERE doc_id=%s AND deleted_at IS NULL ORDER BY chunk_index",
                    (doc_id,),
                )
                rows = cur.fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def list_by_domain(self, domain: str, limit: int = 20) -> list[dict]:
        """Return documents tagged with a specific domain from their meta JSON."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, title, JSON_UNQUOTE(JSON_EXTRACT(meta, '$.concept')) AS concept
                    FROM documents
                    WHERE JSON_EXTRACT(meta, '$.domain') = %s
                      AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (domain, limit),
                )
                rows = cur.fetchall()
        return [{"id": r["id"], "title": r["title"] or "", "concept": r["concept"] or ""} for r in rows]

    def fulltext_search(self, query: str, limit: int = 5) -> list[ChunkRecord]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM doc_chunks
                    WHERE deleted_at IS NULL
                      AND MATCH(content) AGAINST (%s IN BOOLEAN MODE)
                    LIMIT %s
                    """,
                    (query, limit),
                )
                rows = cur.fetchall()
        if not rows:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM doc_chunks WHERE deleted_at IS NULL AND content LIKE %s LIMIT %s",
                        (f"%{query}%", limit),
                    )
                    rows = cur.fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def _row_to_chunk(self, row: dict) -> ChunkRecord:
        return ChunkRecord(
            id=row["id"],
            doc_id=row["doc_id"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            is_indexed=bool(row["is_indexed"]),
            meta=json.loads(row["meta"]) if row["meta"] else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            deleted_at=str(row["deleted_at"]) if row["deleted_at"] else None,
        )
