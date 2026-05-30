from __future__ import annotations

from infra.accounts.models import ExternalAccount
from infra.accounts.service import AccountService


class _FakeStore:
    def __init__(self) -> None:
        self.rows: dict[str, ExternalAccount] = {}
        self.by_interactor: dict[str, ExternalAccount] = {}

    def init_schema(self) -> None:
        pass

    def insert(self, account: ExternalAccount) -> None:
        self.rows[account.account_id] = account
        self.by_interactor[account.interactor_id] = account

    def list_all(self) -> list[ExternalAccount]:
        return list(self.rows.values())

    def get(self, account_id: str) -> ExternalAccount | None:
        return self.rows.get(account_id)

    def get_by_interactor(self, interactor_id: str) -> ExternalAccount | None:
        return self.by_interactor.get(interactor_id)


def test_create_account_invokes_visitor_hook():
    store = _FakeStore()
    registered: list[tuple[str, str, dict]] = []

    def hook(iid: str, name: str, meta: dict) -> None:
        registered.append((iid, name, meta))

    svc = AccountService(store, on_visitor_registered=hook)
    acc = svc.create("荧", meta={"aliases": ["Ying"]})
    assert acc.display_name == "荧"
    assert acc.account_id
    assert acc.interactor_id
    assert store.get(acc.account_id) is not None
    assert len(registered) == 1
    assert registered[0][0] == acc.interactor_id
    assert registered[0][1] == "荧"
    assert registered[0][2]["aliases"] == ["Ying"]


def test_interactor_ids_are_unique_per_account():
    store = _FakeStore()
    svc = AccountService(store)
    a = svc.create("A")
    b = svc.create("B")
    assert a.interactor_id != b.interactor_id
