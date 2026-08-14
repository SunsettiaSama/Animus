from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class PlanHistoryStore:
    def __init__(self, history_dir: str) -> None:
        self._dir = Path(history_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: dict[str, Any]) -> None:
        plan_id = record.get("plan_id", "unknown")
        path = self._dir / f"{plan_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_all(self) -> list[dict]:
        records: list[dict] = []
        for p in self._dir.glob("*.json"):
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw)
            records.append(data)
        records.sort(key=lambda r: r.get("completed_at", 0), reverse=True)
        return records

    def get(self, plan_id: str) -> dict | None:
        path = self._dir / f"{plan_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, plan_id: str) -> None:
        path = self._dir / f"{plan_id}.json"
        if path.exists():
            path.unlink()
