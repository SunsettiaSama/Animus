from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from state import get_state

router = APIRouter()


def _soul_config_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.normpath(os.path.join(here, "..", "..", ".."))
    return os.path.join(project_root, "config", "soul", "config.yaml")


def _resolve_soul():
    state = get_state()
    tao = getattr(state, "active_tao", None)
    if tao is not None:
        soul = getattr(tao, "_soul", None)
        if soul is not None:
            return soul
    agent = getattr(state, "agent_service", None)
    if agent is not None:
        return getattr(agent, "_soul_service", None)
    return None


def _soul_or_400():
    soul = _resolve_soul()
    if soul is None:
        return None, JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "detail": "Soul 未就绪：请先初始化 ReAct（persona + MySQL）。",
            },
        )
    return soul, None


class MemorySearchRequest(BaseModel):
    mode: str = Field(
        "hybrid",
        description="recent | semantic | by_valence | by_field | hybrid",
    )
    query: str = ""
    top_k: int = Field(5, ge=1, le=50)
    limit: int | None = None
    valence: str | None = None
    memory_type: str | None = None
    emotion_hint: str = ""
    chapter: str | None = None
    source_id: str | None = None
    emotion_contains: str | None = None
    created_after: str | None = None
    created_before: str | None = None
    w_relevance: float = 0.6
    w_activation: float = 0.4


@router.get("/api/soul/config")
def get_soul_config():
    from config.soul.config import SoulConfig

    cfg = SoulConfig.from_yaml(_soul_config_path())
    return {"config": cfg.to_dict(), "path": _soul_config_path()}


@router.post("/api/soul/config/save")
def save_soul_config(body: dict[str, Any]):
    from config.soul.config import SoulConfig

    cfg = SoulConfig.from_dict(body.get("config") or body)
    path = _soul_config_path()
    cfg.save_yaml(path)
    return {"status": "ok", "path": path}


@router.get("/api/soul/status")
def get_soul_status():
    soul, err = _soul_or_400()
    if err is not None:
        return err
    return soul.status()


@router.get("/api/soul/persona")
def get_persona_snapshot():
    soul, err = _soul_or_400()
    if err is not None:
        return err
    return soul.query_persona()


@router.post("/api/soul/memory/search")
def post_memory_search(req: MemorySearchRequest):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    payload = req.model_dump(exclude_none=True)
    mode = payload.pop("mode", "hybrid")
    if mode in ("semantic", "hybrid", "smart", "recall") and not payload.get("query"):
        return JSONResponse(
            status_code=422,
            content={"detail": "mode 为 semantic/hybrid 时需要 query"},
        )
    return soul.search_memory(mode, **payload)


@router.get("/api/soul/life/chronicle")
def get_life_chronicle(days: int = 7, tail: int = 50):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    return {
        "days": days,
        "tail": tail,
        "count": len(entries := soul.query_life_chronicle(days=days, tail=tail)),
        "entries": entries,
    }


@router.get("/api/soul/life/hot")
def get_life_hot(hours: int | None = None):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    units = soul.query_life_hot(hours=hours)
    return {
        "hours": hours,
        "count": len(units),
        "experiences": units,
    }
