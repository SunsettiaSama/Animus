from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.soul.memory.domain import InteractorRef

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient


class MySQLInteractorStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def get(self, interactor_id: str) -> InteractorRef | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM soul_interactors WHERE id=%s",
                    (interactor_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return InteractorRef(
            id=row["id"],
            display_name=row.get("display_name") or "",
            created_at=row["created_at"],
        )

    def get_or_create(self, interactor_id: str, *, display_name: str = "") -> InteractorRef:
        existing = self.get(interactor_id)
        if existing is not None:
            return existing
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO soul_interactors (id, display_name, created_at)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)
                    """,
                    (interactor_id, display_name, now),
                )
        ref = self.get(interactor_id)
        if ref is None:
            raise RuntimeError(f"failed to create interactor {interactor_id!r}")
        return ref
