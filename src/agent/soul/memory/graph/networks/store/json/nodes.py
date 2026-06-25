from __future__ import annotations

import math
import json
from datetime import datetime, timezone

from agent.soul.memory.domain import MemoryNetwork, SocialNodeRole
from agent.soul.memory.graph.base_node import BaseNode
from agent.soul.memory.graph.networks.store.codec import node_to_row_params, row_to_node
from infra.storage import JsonStorageService


def _utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _as_dt(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class JsonNodeStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("memory/nodes")

    def init_schema(self) -> None:
        self._rows.all()

    def put(self, node: BaseNode) -> None:
        row = node_to_row_params(node)
        current = self._rows.get(node.id) or {}
        row["archived"] = int(current.get("archived") or 0)
        row["archived_at"] = current.get("archived_at")
        self._rows.upsert(node.id, row)

    def get(self, node_id: str) -> BaseNode | None:
        row = self._rows.get(node_id)
        if row is None or int(row.get("archived") or 0):
            return None
        return row_to_node(row)

    def get_many(self, node_ids: list[str]) -> list[BaseNode]:
        wanted = set(node_ids)
        rows = [
            row for row in self._rows.all()
            if row.get("id") in wanted and not int(row.get("archived") or 0)
        ]
        order = {node_id: idx for idx, node_id in enumerate(node_ids)}
        rows.sort(key=lambda row: order.get(str(row.get("id")), len(order)))
        return [row_to_node(row) for row in rows]

    def list_by_network(self, network: MemoryNetwork, *, limit: int = 50) -> list[BaseNode]:
        rows = self._active_rows(
            lambda row: row.get("network") == network.value,
            sort_key=lambda row: str(row.get("last_accessed") or ""),
        )
        return [row_to_node(row) for row in rows[:limit]]

    def list_by_interactor(
        self,
        interactor_id: str,
        role: SocialNodeRole | None = None,
        *,
        limit: int = 50,
    ) -> list[BaseNode]:
        def _match(row: dict) -> bool:
            if row.get("interactor_id") != interactor_id:
                return False
            return role is None or row.get("node_role") == role.value

        rows = self._active_rows(_match, sort_key=lambda row: str(row.get("last_accessed") or ""))
        return [row_to_node(row) for row in rows[:limit]]

    def list_recent(
        self,
        memory_type: str | None = None,
        valence=None,
        network: MemoryNetwork | None = None,
        limit: int = 50,
    ) -> list[BaseNode]:
        def _match(row: dict) -> bool:
            if memory_type and row.get("memory_type") != memory_type:
                return False
            if valence is not None and row.get("valence") != valence.value:
                return False
            return network is None or row.get("network") == network.value

        rows = self._active_rows(_match, sort_key=lambda row: str(row.get("last_accessed") or ""))
        return [row_to_node(row) for row in rows[:limit]]

    def list_all(self, limit: int = 2000, network: MemoryNetwork | None = None) -> list[BaseNode]:
        rows = self._active_rows(
            lambda row: network is None or row.get("network") == network.value,
            sort_key=lambda row: str(row.get("last_accessed") or ""),
        )
        return [row_to_node(row) for row in rows[:limit]]

    def query_by_fields(
        self,
        memory_type: str | None = None,
        valence=None,
        chapter: str | None = None,
        source_id: str | None = None,
        emotion_contains: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 50,
        network: MemoryNetwork | None = None,
    ) -> list[BaseNode]:
        def _match(row: dict) -> bool:
            if memory_type and row.get("memory_type") != memory_type:
                return False
            if valence is not None and row.get("valence") != valence.value:
                return False
            if chapter and row.get("chapter") != chapter:
                return False
            if source_id and row.get("source_id") != source_id:
                return False
            if emotion_contains and emotion_contains not in str(row.get("emotion") or ""):
                return False
            created = str(row.get("created_at") or "")
            if created_after and created < created_after:
                return False
            if created_before and created > created_before:
                return False
            return network is None or row.get("network") == network.value

        rows = self._active_rows(_match, sort_key=lambda row: str(row.get("last_accessed") or ""))
        return [row_to_node(row) for row in rows[:limit]]

    def get_by_life_event_id(self, life_event_id: str) -> BaseNode | None:
        if not life_event_id:
            return None
        for row in self._active_rows(lambda item: True):
            meta = json.loads(row.get("meta_json") or "{}")
            if str(meta.get("life_event_id") or "") == life_event_id:
                return row_to_node(row)
        return None

    def get_core_for_interactor(self, interactor_id: str) -> BaseNode | None:
        nodes = self.list_by_interactor(interactor_id, SocialNodeRole.core, limit=1)
        return nodes[0] if nodes else None

    def on_recall(self, node_id: str) -> None:
        self._bump(node_id, "recall_count")

    def add_rehearsal(self, node_id: str) -> None:
        self._bump(node_id, "rehearsal_count")

    def add_narrative_ref(self, node_id: str) -> None:
        self._bump(node_id, "narrative_ref_count", touch=False)

    def archive(self, node_id: str) -> None:
        row = self._rows.get(node_id)
        if row is None:
            return
        row["archived"] = 1
        row["archived_at"] = _utc_str()
        self._rows.upsert(node_id, row)

    def forget_scan(
        self,
        *,
        threshold: float = 0.05,
        half_life_days: float = 30.0,
        dry_run: bool = False,
        network: MemoryNetwork | None = None,
    ) -> list[str]:
        rows = self._active_rows(lambda row: network is None or row.get("network") == network.value)
        now = datetime.now(timezone.utc)
        to_archive: list[str] = []
        for row in rows:
            last = _as_dt(row["last_accessed"])
            delta = (now - last).total_seconds() / 86400.0
            decay = math.exp(-math.log(2) / half_life_days * max(delta, 0.0))
            boost = math.log1p(int(row.get("recall_count") or 0))
            activation = min(1.0, float(row.get("base_activation") or 0.5) * decay + boost)
            if activation < threshold:
                to_archive.append(str(row["id"]))
        if not dry_run:
            for uid in to_archive:
                self.archive(uid)
        return to_archive

    def _bump(self, node_id: str, field: str, *, touch: bool = True) -> None:
        row = self._rows.get(node_id)
        if row is None:
            return
        row[field] = int(row.get(field) or 0) + 1
        if touch:
            row["last_accessed"] = _utc_str()
        self._rows.upsert(node_id, row)

    def _active_rows(self, predicate, *, sort_key=None) -> list[dict]:
        rows = [
            row for row in self._rows.all()
            if not int(row.get("archived") or 0) and predicate(row)
        ]
        if sort_key is not None:
            rows.sort(key=sort_key, reverse=True)
        return rows
