from __future__ import annotations

from datetime import datetime, timezone

from infra.storage import JsonStorageService


def _utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class JsonSessionChannelStore:
    """Web/channel session_id -> interactor_id mapping for JSON fallback."""

    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("memory/session_channels")

    def get_interactor(self, session_id: str) -> str:
        sid = session_id.strip()
        if not sid:
            return ""
        row = self._rows.get(sid)
        if row is None:
            return ""
        return str(row.get("interactor_id") or "").strip()

    def bind(self, session_id: str, interactor_id: str) -> None:
        sid = session_id.strip()
        iid = interactor_id.strip()
        if not sid or not iid:
            return
        self._rows.upsert(
            sid,
            {
                "session_id": sid,
                "interactor_id": iid,
                "bound_at": _utc_str(),
            },
        )
