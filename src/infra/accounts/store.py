from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from infra.db.mysql import MySQLClient
from infra.storage import JsonStorageService

from .models import ExternalAccount

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


@runtime_checkable
class AccountStore(Protocol):
    def insert(self, account: ExternalAccount) -> None: ...
    def list_all(self) -> list[ExternalAccount]: ...
    def get(self, account_id: str) -> ExternalAccount | None: ...
    def get_by_interactor(self, interactor_id: str) -> ExternalAccount | None: ...


class MySQLAccountStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def init_schema(self) -> None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            sql = f.read()
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)

    def insert(self, account: ExternalAccount) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO external_accounts (
                        account_id, interactor_id, display_name, meta_json, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        account.account_id,
                        account.interactor_id,
                        account.display_name,
                        json.dumps(account.meta, ensure_ascii=False),
                        now,
                        now,
                    ),
                )

    def list_all(self) -> list[ExternalAccount]:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM external_accounts ORDER BY updated_at DESC"
                )
                rows = cur.fetchall()
        return [ExternalAccount.from_row(r) for r in rows]

    def get(self, account_id: str) -> ExternalAccount | None:
        aid = account_id.strip()
        if not aid:
            return None
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM external_accounts WHERE account_id=%s",
                    (aid,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return ExternalAccount.from_row(row)


class JsonAccountStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("accounts")

    def insert(self, account: ExternalAccount) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "account_id": account.account_id,
            "interactor_id": account.interactor_id,
            "display_name": account.display_name,
            "meta_json": json.dumps(account.meta, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        self._rows.upsert(account.account_id, row)

    def list_all(self) -> list[ExternalAccount]:
        rows = self._rows.all()
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return [ExternalAccount.from_row(row) for row in rows]

    def get(self, account_id: str) -> ExternalAccount | None:
        row = self._rows.get(account_id.strip())
        return ExternalAccount.from_row(row) if row else None

    def get_by_interactor(self, interactor_id: str) -> ExternalAccount | None:
        iid = interactor_id.strip()
        if not iid:
            return None
        rows = self._rows.filter(lambda row: row.get("interactor_id") == iid)
        if not rows:
            return None
        return ExternalAccount.from_row(rows[0])

    def get_by_interactor(self, interactor_id: str) -> ExternalAccount | None:
        iid = interactor_id.strip()
        if not iid:
            return None
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM external_accounts WHERE interactor_id=%s",
                    (iid,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return ExternalAccount.from_row(row)
