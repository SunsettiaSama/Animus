from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from routers.soul import _soul_or_400

router = APIRouter()


class CreateAccountBody(BaseModel):
    display_name: str
    meta: dict | None = None


@router.get("/api/accounts")
def list_accounts():
    soul, err = _soul_or_400()
    if err is not None:
        return err
    rows = soul.accounts.list_accounts()
    return {"accounts": [a.to_dict() for a in rows]}


@router.post("/api/accounts")
def create_account(body: CreateAccountBody):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    account = soul.accounts.create(body.display_name, meta=body.meta)
    return {"account": account.to_dict()}


@router.get("/api/accounts/{account_id}")
def get_account(account_id: str):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    account = soul.accounts.get(account_id)
    if account is None:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "detail": f"未知账号 {account_id!r}"},
        )
    return {"account": account.to_dict()}
