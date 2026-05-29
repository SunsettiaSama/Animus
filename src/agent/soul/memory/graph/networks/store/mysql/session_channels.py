from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient


class MySQLSessionChannelStore:
    """Web/渠道 session_id → 已识别 interactor_id（跨重启保持「认出对方」）。"""

    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def get_interactor(self, session_id: str) -> str:
        sid = session_id.strip()
        if not sid:
            return ""
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT interactor_id FROM soul_session_channels WHERE session_id=%s",
                    (sid,),
                )
                row = cur.fetchone()
        if not row:
            return ""
        return str(row.get("interactor_id") or "").strip()

    def bind(self, session_id: str, interactor_id: str) -> None:
        sid = session_id.strip()
        iid = interactor_id.strip()
        if not sid or not iid:
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO soul_session_channels (session_id, interactor_id, bound_at)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        interactor_id=VALUES(interactor_id),
                        bound_at=VALUES(bound_at)
                    """,
                    (sid, iid, now),
                )
