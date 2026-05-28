from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.memory.domain import MemoryNetwork, SocialNodeRole, Valence
from agent.soul.memory.store.mysql.nodes import MySQLNodeStore
from agent.soul.memory.unit import MemoryUnit

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient


class LongTermMemoryManager:
    """向后兼容薄包装：委托 ``MySQLNodeStore``。"""

    def __init__(self, mysql_client: MySQLClient) -> None:
        self._nodes = MySQLNodeStore(mysql_client)

    def init_schema(self) -> None:
        self._nodes.init_schema()

    def put(self, unit: MemoryUnit) -> None:
        self._nodes.put(unit)

    def get(self, unit_id: str) -> MemoryUnit | None:
        return self._nodes.get(unit_id)

    def get_many(self, unit_ids: list[str]) -> list[MemoryUnit]:
        return self._nodes.get_many(unit_ids)

    def list_recent(
        self,
        memory_type: str | None = None,
        valence: Valence | None = None,
        limit: int = 50,
    ) -> list[MemoryUnit]:
        return self._nodes.list_recent(memory_type=memory_type, valence=valence, limit=limit)

    def list_all(self, limit: int = 2000) -> list[MemoryUnit]:
        return self._nodes.list_all(limit=limit)

    def query_by_fields(self, **kwargs) -> list[MemoryUnit]:
        return self._nodes.query_by_fields(**kwargs)

    def get_by_life_event_id(self, life_event_id: str) -> MemoryUnit | None:
        return self._nodes.get_by_life_event_id(life_event_id)

    def get_reconstructions_of(self, source_id: str) -> list[MemoryUnit]:
        return self._nodes.query_by_fields(source_id=source_id, memory_type="reconstructive")

    def on_recall(self, unit_id: str) -> None:
        self._nodes.on_recall(unit_id)

    def add_rehearsal(self, unit_id: str) -> None:
        self._nodes.add_rehearsal(unit_id)

    def add_narrative_ref(self, unit_id: str) -> None:
        self._nodes.add_narrative_ref(unit_id)

    def archive(self, unit_id: str) -> None:
        self._nodes.archive(unit_id)

    def archive_by_life_event_id(self, life_event_id: str) -> bool:
        unit = self.get_by_life_event_id(life_event_id)
        if unit is None:
            return False
        self.archive(unit.id)
        return True

    def purge(self, unit_id: str) -> None:
        self._nodes.archive(unit_id)

    def forget_scan(self, threshold: float = 0.05, half_life_days: float = 30.0, dry_run: bool = False) -> list[str]:
        return self._nodes.forget_scan(
            threshold=threshold,
            half_life_days=half_life_days,
            dry_run=dry_run,
            network=MemoryNetwork.event,
        )

    def count(self, memory_type: str | None = None) -> int:
        units = self._nodes.list_all(limit=10000)
        if memory_type:
            return sum(1 for u in units if u.MEMORY_TYPE == memory_type)
        return len(units)

    @property
    def nodes(self) -> MySQLNodeStore:
        return self._nodes
