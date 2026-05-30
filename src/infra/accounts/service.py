from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from infra.db.mysql import MySQLClient

from .models import ExternalAccount
from .store import MySQLAccountStore

if TYPE_CHECKING:
    pass

VisitorRegisteredHook = Callable[[str, str, dict], None]


class AccountService:
    """外部来访用户元数据：account_id ↔ 固定 interactor_id（Memory 图身份键）。"""

    def __init__(
        self,
        store: MySQLAccountStore,
        *,
        on_visitor_registered: VisitorRegisteredHook | None = None,
    ) -> None:
        self._store = store
        self._on_visitor_registered = on_visitor_registered

    @classmethod
    def build(
        cls,
        mysql_client: MySQLClient,
        *,
        on_visitor_registered: VisitorRegisteredHook | None = None,
        init_schema: bool = True,
    ) -> AccountService:
        store = MySQLAccountStore(mysql_client)
        if init_schema:
            store.init_schema()
        return cls(store, on_visitor_registered=on_visitor_registered)

    def set_visitor_hook(self, hook: VisitorRegisteredHook | None) -> None:
        self._on_visitor_registered = hook

    def list_accounts(self) -> list[ExternalAccount]:
        return self._store.list_all()

    def get(self, account_id: str) -> ExternalAccount | None:
        return self._store.get(account_id)

    def get_by_interactor(self, interactor_id: str) -> ExternalAccount | None:
        return self._store.get_by_interactor(interactor_id)

    def create(
        self,
        display_name: str,
        *,
        meta: dict | None = None,
    ) -> ExternalAccount:
        name = display_name.strip()
        if not name:
            raise ValueError("display_name 不能为空")
        account_id = str(uuid.uuid4())
        interactor_id = str(uuid.uuid4())
        meta_dict = dict(meta or {})
        account = ExternalAccount(
            account_id=account_id,
            interactor_id=interactor_id,
            display_name=name,
            meta=meta_dict,
        )
        self._store.insert(account)
        if self._on_visitor_registered is not None:
            self._on_visitor_registered(interactor_id, name, meta_dict)
        return account
