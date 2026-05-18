from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.soul.memory.codec import unit_from_dict, unit_to_dict
from agent.soul.memory.unit import MemoryTier, MemoryUnit, Valence

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

_INSERT_SQL = """
INSERT INTO soul_memory_units (
    id, memory_type, focus, emotion, emotion_intensity, valence,
    tier, base_activation, recall_count, rehearsal_count, narrative_ref_count,
    last_accessed, created_at, meta_json,
    fact, perception,
    source_id, reconstructed_fact, trigger_ctx,
    narrative, source_ids_json, chapter
) VALUES (
    %(id)s, %(memory_type)s, %(focus)s, %(emotion)s, %(emotion_intensity)s, %(valence)s,
    %(tier)s, %(base_activation)s, %(recall_count)s, %(rehearsal_count)s, %(narrative_ref_count)s,
    %(last_accessed)s, %(created_at)s, %(meta_json)s,
    %(fact)s, %(perception)s,
    %(source_id)s, %(reconstructed_fact)s, %(trigger_ctx)s,
    %(narrative)s, %(source_ids_json)s, %(chapter)s
)
ON DUPLICATE KEY UPDATE
    focus                = VALUES(focus),
    emotion              = VALUES(emotion),
    emotion_intensity    = VALUES(emotion_intensity),
    valence              = VALUES(valence),
    tier                 = VALUES(tier),
    base_activation      = VALUES(base_activation),
    recall_count         = VALUES(recall_count),
    rehearsal_count      = VALUES(rehearsal_count),
    narrative_ref_count  = VALUES(narrative_ref_count),
    last_accessed        = VALUES(last_accessed),
    meta_json            = VALUES(meta_json),
    fact                 = VALUES(fact),
    perception           = VALUES(perception),
    reconstructed_fact   = VALUES(reconstructed_fact),
    trigger_ctx          = VALUES(trigger_ctx),
    narrative            = VALUES(narrative),
    source_ids_json      = VALUES(source_ids_json),
    chapter              = VALUES(chapter)
"""


def _dt_fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_params(unit: MemoryUnit) -> dict:
    d = unit_to_dict(unit)
    return {
        "id":                d["id"],
        "memory_type":       d["memory_type"],
        "focus":             d["focus"],
        "emotion":           d["emotion"],
        "emotion_intensity": d["emotion_intensity"],
        "valence":           d["valence"],
        "tier":              d["tier"],
        "base_activation":   d["base_activation"],
        "recall_count":        d["recall_count"],
        "rehearsal_count":     d["rehearsal_count"],
        "narrative_ref_count": d["narrative_ref_count"],
        "last_accessed":       _dt_fmt(unit.last_accessed),
        "created_at":        _dt_fmt(unit.created_at),
        "meta_json":         json.dumps(d.get("meta") or {}, ensure_ascii=False),
        "fact":              d.get("fact"),
        "perception":        d.get("perception"),
        "source_id":         d.get("source_id"),
        "reconstructed_fact": d.get("reconstructed_fact"),
        "trigger_ctx":       d.get("trigger"),
        "narrative":         d.get("narrative"),
        "source_ids_json":   json.dumps(d.get("source_ids") or [], ensure_ascii=False),
        "chapter":           d.get("chapter", ""),
    }


def _row_to_unit(row: dict) -> MemoryUnit:
    d: dict = {
        "memory_type":       row["memory_type"],
        "id":                row["id"],
        "focus":             row["focus"],
        "emotion":           row.get("emotion") or "",
        "emotion_intensity": float(row.get("emotion_intensity") or 0.0),
        "valence":           row.get("valence") or "neutral",
        "tier":              row.get("tier") or "short_term",
        "base_activation":   float(row.get("base_activation") or 0.5),
        "recall_count":        int(row.get("recall_count") or 0),
        "rehearsal_count":     int(row.get("rehearsal_count") or 0),
        "narrative_ref_count": int(row.get("narrative_ref_count") or 0),
        "last_accessed":     str(row["last_accessed"]),
        "created_at":        str(row["created_at"]),
        "meta":              json.loads(row["meta_json"]) if row.get("meta_json") else {},
        "fact":              row.get("fact") or "",
        "perception":        row.get("perception") or "",
        "source_id":         row.get("source_id") or "",
        "reconstructed_fact": row.get("reconstructed_fact") or "",
        "trigger":           row.get("trigger_ctx") or "",
        "narrative":         row.get("narrative") or "",
        "source_ids":        json.loads(row["source_ids_json"]) if row.get("source_ids_json") else [],
        "chapter":           row.get("chapter") or "",
    }
    return unit_from_dict(d)


class LongTermMemoryManager:
    """长期记忆管理器（MySQL 后端）。

    职责
    ----
    - put / get / delete MemoryUnit（tier=long）
    - on_recall：命中时 UPDATE recall_count + last_accessed
    - forget_scan：软删除激活度低于阈值的条目（archived=1）
    - init_schema：建表（应用启动时调用一次）

    Qdrant 向量检索
    ---------------
    本管理器仅负责结构化字段的 CRUD。语义检索（向量索引、混合重排）
    由独立的 Retriever 模块负责，Retriever 按需从本管理器获取完整 unit。

    使用
    ----
        mysql_client = MySQLClient("mysql+pymysql://user:pass@host/db")
        lt = LongTermMemoryManager(mysql_client)
        lt.init_schema()
        lt.put(unit)
    """

    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    # ── Schema ────────────────────────────────────────────────────────────────

    def init_schema(self) -> None:
        """执行 schema.sql，建表（幂等，IF NOT EXISTS）。"""
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            sql = f.read()
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)

    # ── Write ─────────────────────────────────────────────────────────────────

    def put(self, unit: MemoryUnit) -> None:
        """写入或更新长期记忆（ON DUPLICATE KEY UPDATE）。"""
        params = _row_to_params(unit)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT_SQL, params)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, unit_id: str) -> MemoryUnit | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM soul_memory_units WHERE id=%s AND archived=0",
                    (unit_id,),
                )
                row = cur.fetchone()
        return _row_to_unit(row) if row else None

    def get_many(self, unit_ids: list[str]) -> list[MemoryUnit]:
        if not unit_ids:
            return []
        placeholders = ",".join(["%s"] * len(unit_ids))
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM soul_memory_units WHERE id IN ({placeholders}) AND archived=0",
                    unit_ids,
                )
                rows = cur.fetchall()
        return [_row_to_unit(r) for r in rows]

    def list_recent(
        self,
        memory_type: str | None = None,
        valence: Valence | None = None,
        limit: int = 50,
    ) -> list[MemoryUnit]:
        """按 last_accessed 倒序列出长期记忆，支持按类型/情感倾向过滤。"""
        conds = ["archived=0"]
        params: list = []
        if memory_type:
            conds.append("memory_type=%s")
            params.append(memory_type)
        if valence:
            conds.append("valence=%s")
            params.append(valence.value)
        where = " AND ".join(conds)
        params.append(limit)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM soul_memory_units WHERE {where} ORDER BY last_accessed DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()
        return [_row_to_unit(r) for r in rows]

    def query_by_fields(
        self,
        memory_type: str | None = None,
        valence: Valence | None = None,
        chapter: str | None = None,
        source_id: str | None = None,
        emotion_contains: str | None = None,
        created_after: str | None = None,   # ISO datetime string
        created_before: str | None = None,  # ISO datetime string
        limit: int = 50,
    ) -> list[MemoryUnit]:
        """结构化字段查询，支持多条件组合过滤。

        所有参数均为可选，不传则该维度不参与过滤。
        多个条件之间为 AND 关系。
        """
        conds = ["archived=0"]
        params: list = []

        if memory_type:
            conds.append("memory_type=%s")
            params.append(memory_type)
        if valence:
            conds.append("valence=%s")
            params.append(valence.value)
        if chapter:
            conds.append("chapter=%s")
            params.append(chapter)
        if source_id:
            conds.append("source_id=%s")
            params.append(source_id)
        if emotion_contains:
            conds.append("emotion LIKE %s")
            params.append(f"%{emotion_contains}%")
        if created_after:
            conds.append("created_at >= %s")
            params.append(created_after)
        if created_before:
            conds.append("created_at <= %s")
            params.append(created_before)

        where = " AND ".join(conds)
        params.append(limit)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM soul_memory_units WHERE {where} "
                    f"ORDER BY last_accessed DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()
        return [_row_to_unit(r) for r in rows]

    def get_reconstructions_of(self, source_id: str) -> list[MemoryUnit]:
        """返回 ``source_id`` 指向的直接子重构（下一跳 ReconstructiveMemory）列表。"""
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM soul_memory_units WHERE source_id=%s AND archived=0 ORDER BY created_at",
                    (source_id,),
                )
                rows = cur.fetchall()
        return [_row_to_unit(r) for r in rows]

    # ── Recall update ────────────────────────────────────────────────────────

    def on_recall(self, unit_id: str) -> None:
        """命中后更新 recall_count + last_accessed。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE soul_memory_units SET recall_count=recall_count+1, last_accessed=%s WHERE id=%s",
                    (now, unit_id),
                )

    def add_rehearsal(self, unit_id: str) -> None:
        """心跳反刍后更新 rehearsal_count + last_accessed。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE soul_memory_units SET rehearsal_count=rehearsal_count+1, last_accessed=%s WHERE id=%s",
                    (now, unit_id),
                )

    def add_narrative_ref(self, unit_id: str) -> None:
        """NarrativeMemory 引用该记忆时递增 narrative_ref_count。"""
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE soul_memory_units SET narrative_ref_count=narrative_ref_count+1 WHERE id=%s",
                    (unit_id,),
                )

    # ── Delete / Archive ──────────────────────────────────────────────────────

    def archive(self, unit_id: str) -> None:
        """软删除：标记 archived=1，保留数据用于审计。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE soul_memory_units SET archived=1, archived_at=%s WHERE id=%s",
                    (now, unit_id),
                )

    def purge(self, unit_id: str) -> None:
        """物理删除（归档超过 retention_days 后调用）。"""
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM soul_memory_units WHERE id=%s", (unit_id,))

    # ── Forgetting ────────────────────────────────────────────────────────────

    def forget_scan(
        self,
        threshold: float = 0.05,
        half_life_days: float = 30.0,
        dry_run: bool = False,
    ) -> list[str]:
        """遗忘扫描：对激活度低于 threshold 的条目执行软删除。

        激活度在 Python 层实时计算（懒计算策略），不依赖 DB 存储激活值。
        返回被归档的 unit_id 列表。

        dry_run=True 时只返回候选 id，不执行归档。
        """
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, base_activation, recall_count, last_accessed
                    FROM soul_memory_units
                    WHERE archived=0
                    """,
                )
                rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        to_archive: list[str] = []
        for row in rows:
            last = row["last_accessed"]
            if isinstance(last, str):
                last = datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
            elif last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)

            delta = (now - last).total_seconds() / 86400.0
            import math
            decay = math.exp(-math.log(2) / half_life_days * max(delta, 0.0))
            boost = math.log1p(int(row["recall_count"] or 0))
            activation = min(1.0, float(row["base_activation"] or 0.5) * decay + boost)

            if activation < threshold:
                to_archive.append(row["id"])

        if not dry_run:
            for uid in to_archive:
                self.archive(uid)

        return to_archive

    # ── Stats ─────────────────────────────────────────────────────────────────

    def count(self, memory_type: str | None = None) -> int:
        cond = "archived=0"
        params: list = []
        if memory_type:
            cond += " AND memory_type=%s"
            params.append(memory_type)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) AS n FROM soul_memory_units WHERE {cond}",
                    params,
                )
                row = cur.fetchone()
        return int(row["n"]) if row else 0
