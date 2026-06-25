from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.memory.domain import InteractorRef
from infra.storage import JsonStorageService


def _utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class JsonInteractorStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("memory/interactors")

    def get(self, interactor_id: str) -> InteractorRef | None:
        row = self._rows.get(interactor_id)
        if row is None:
            return None
        return InteractorRef(
            id=str(row["id"]),
            display_name=str(row.get("display_name") or ""),
            created_at=row.get("created_at") or "",
        )

    def get_or_create(self, interactor_id: str, *, display_name: str = "") -> InteractorRef:
        existing = self.get(interactor_id)
        if existing is not None:
            return existing
        row = {
            "id": interactor_id,
            "display_name": display_name,
            "created_at": _utc_str(),
        }
        self._rows.upsert(interactor_id, row)
        return InteractorRef(
            id=interactor_id,
            display_name=display_name,
            created_at=row["created_at"],
        )
