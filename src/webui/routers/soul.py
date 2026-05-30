from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from state import get_state

router = APIRouter()


def _project_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", ".."))


def _soul_config_path() -> str:
    return os.path.join(_project_root(), "config", "soul", "config.yaml")


def _memory_service_path() -> str:
    return os.path.join(_project_root(), "config", "soul", "memory", "service.yaml")


def _memory_infra_path() -> str:
    return os.path.join(_project_root(), "config", "soul", "memory", "infra.yaml")


def _load_persona_cfg_dict() -> dict:
    state = get_state()
    if not os.path.exists(state.persona_cfg_file):
        return {}
    with open(state.persona_cfg_file, encoding="utf-8") as f:
        return json.load(f)


def _persona_file_flags() -> dict[str, bool]:
    state = get_state()
    persona_dir = state.persona_dir
    return {
        "profile_exists": os.path.isfile(os.path.join(persona_dir, "profile.json")),
        "built_profile_exists": os.path.isfile(
            os.path.join(persona_dir, "built_profile.json")
        ),
        "self_concept_exists": os.path.isfile(
            os.path.join(persona_dir, "self_concept.json")
        ),
    }


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


class PersonaRebuildRequest(BaseModel):
    preserve_self_concept: bool = False


@router.get("/api/soul/readiness")
def get_soul_readiness():
    """Soul 启动前置条件与当前运行态（供前端初始化面板）。"""
    state = get_state()
    persona_cfg = _load_persona_cfg_dict()
    persona_enabled = bool(persona_cfg.get("enabled", False))
    files = _persona_file_flags()

    from config.infra.db_config import DBConfig

    db_cfg = DBConfig.load_default()
    mysql_enabled = bool(db_cfg.mysql.enabled)

    llm_ready = bool(
        getattr(state, "llm_service", None) is not None
        and getattr(state.llm_service, "handle", None) is not None
    )
    react_ready = getattr(state, "conv_loop", None) is not None

    soul = _resolve_soul()
    soul_state = getattr(soul, "state", None) if soul is not None else None
    soul_running = bool(soul is not None and soul.is_running)

    speak_ready = False
    if soul_running:
        speak_ready = soul._ensure_speak_service() is not None

    checks = [
        {
            "id": "llm",
            "label": "LLM 已加载",
            "ok": llm_ready,
            "hint": "Settings → Core → Save & Apply",
        },
        {
            "id": "persona_enabled",
            "label": "Persona 已启用",
            "ok": persona_enabled,
            "hint": "Settings → Persona → 启用人格演化",
        },
        {
            "id": "mysql",
            "label": "MySQL 已启用",
            "ok": mysql_enabled,
            "hint": "config/infra/db.yaml → mysql.enabled",
        },
        {
            "id": "profile",
            "label": "profile.json 存在",
            "ok": files["profile_exists"],
            "hint": "Settings → Persona → 填写并保存画像",
        },
        {
            "id": "react",
            "label": "ReAct / Soul 已初始化",
            "ok": react_ready and soul is not None,
            "hint": "保存 Persona 后点击「重新初始化 Soul」",
        },
        {
            "id": "built_profile",
            "label": "built_profile.json 已生成",
            "ok": files["built_profile_exists"],
            "hint": "Soul 运行后点击「Build 人格画像」",
            "optional": True,
        },
        {
            "id": "soul_running",
            "label": "Soul 运行中",
            "ok": soul_running,
            "hint": "完成 ReAct 初始化后自动 start()",
        },
    ]

    required_ok = all(c["ok"] for c in checks if not c.get("optional"))
    return {
        "ready": required_ok and soul_running,
        "speak_ready": speak_ready,
        "persona_enabled": persona_enabled,
        "mysql_enabled": mysql_enabled,
        "llm_ready": llm_ready,
        "react_ready": react_ready,
        "soul_state": soul_state,
        "soul_running": soul_running,
        "files": files,
        "checks": checks,
        "paths": {
            "soul_config": _soul_config_path(),
            "memory_service": _memory_service_path(),
            "memory_infra": _memory_infra_path(),
            "persona_dir": state.persona_dir,
        },
    }


@router.post("/api/soul/persona/rebuild")
def post_persona_rebuild(body: PersonaRebuildRequest | None = None):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    if not soul.is_running:
        return JSONResponse(
            status_code=409,
            content={"detail": "Soul 未运行，请先完成初始化"},
        )
    preserve = False if body is None else body.preserve_self_concept
    result = soul.rebuild_persona_profile(preserve_self_concept=preserve)
    files = _persona_file_flags()
    return {"status": "ok", "result": result, "files": files}


@router.post("/api/soul/persona/reload")
def post_persona_reload():
    soul, err = _soul_or_400()
    if err is not None:
        return err
    result = soul.reload_persona_profile()
    return {"status": "ok", "result": result}


@router.get("/api/soul/memory/config")
def get_memory_service_config():
    from config.soul.memory.service_config import MemoryServiceConfig

    path = _memory_service_path()
    cfg = MemoryServiceConfig.from_yaml(path)
    return {"config": cfg.to_dict(), "path": path}


@router.post("/api/soul/memory/config/save")
def save_memory_service_config(body: dict[str, Any]):
    from config.soul.memory.service_config import MemoryServiceConfig

    cfg = MemoryServiceConfig.from_dict(body.get("config") or body)
    path = _memory_service_path()
    cfg.save_yaml(path)
    return {"status": "ok", "path": path}


@router.get("/api/soul/memory/infra")
def get_memory_infra_config():
    from config.soul.memory.infra_config import SoulMemoryInfraConfig

    path = _memory_infra_path()
    cfg = SoulMemoryInfraConfig.from_yaml(path)
    return {"config": cfg.to_dict(), "path": path}


@router.post("/api/soul/memory/infra/save")
def save_memory_infra_config(body: dict[str, Any]):
    from config.soul.memory.infra_config import SoulMemoryInfraConfig

    cfg = SoulMemoryInfraConfig.from_dict(body.get("config") or body)
    path = _memory_infra_path()
    cfg.save_yaml(path)
    return {"status": "ok", "path": path}


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


@router.get("/api/soul/heartbeat-log")
def get_soul_heartbeat_log(n: int = 50):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    if soul.heartbeat is None:
        return {"entries": [], "ready": False}
    return {"entries": soul.heartbeat.recent_log(n=n), "ready": True}


@router.post("/api/soul/heartbeat/tick")
def post_soul_heartbeat_tick():
    soul, err = _soul_or_400()
    if err is not None:
        return err
    if not soul.is_running:
        return JSONResponse(status_code=409, content={"detail": "Soul 未运行"})
    result = soul.force_heartbeat_tick()
    return {
        "ok": True,
        "outcome": result.outcome,
        "reason": result.reason,
        "duration_ms": result.duration_ms,
    }


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


class VisitorBindBody(BaseModel):
    account_id: str
    channel_id: str = ""


@router.post("/api/soul/visitor/bind")
def visitor_bind(body: VisitorBindBody):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    return soul.bind_visitor(body.account_id, body.channel_id)
