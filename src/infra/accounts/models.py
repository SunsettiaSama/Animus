from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ExternalAccount:
    account_id: str
    interactor_id: str
    display_name: str
    meta: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "interactor_id": self.interactor_id,
            "display_name": self.display_name,
            "meta": dict(self.meta),
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }

    @classmethod
    def from_row(cls, row: dict) -> ExternalAccount:
        meta_raw = row.get("meta_json")
        if isinstance(meta_raw, str):
            meta = json.loads(meta_raw) if meta_raw else {}
        elif isinstance(meta_raw, dict):
            meta = meta_raw
        else:
            meta = {}
        return cls(
            account_id=str(row["account_id"]),
            interactor_id=str(row["interactor_id"]),
            display_name=str(row.get("display_name") or ""),
            meta=meta,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
