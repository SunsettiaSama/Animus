from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


class MemorySaveRequest(BaseModel):
    st_enabled: bool = True
    st_max_turns: int = 10
    st_max_tokens: int = 2048
    st_distill_enabled: bool = True
    st_distill_trigger_steps: int = 4
    st_max_distillate_tokens: int = 400

    mt_enabled: bool = True
    mt_window_days: int = 7
    mt_max_entries: int = 30
    mt_max_chars: int = 3000
    mt_consolidate_enabled: bool = True
    mt_consolidate_batch: int = 10
    mt_consolidate_interval_days: int = 1
    mt_max_consolidate_tokens: int = 500

    lt_enabled: bool = False
    lt_top_k: int = 5
    lt_max_recall_chars: int = 3000
    lt_consolidation_k: int = 0
    lt_distill_enabled: bool = False
    lt_max_distill_tokens: int = 400

    ms_enabled: bool = False
    ms_max_milestones: int = 50
    ms_importance_threshold: float = 0.6
    ms_top_k_retrieve: int = 2
    ms_inject_detail: bool = True


def _load_memory_config():
    from config.agent.memory.memory_config import MemoryConfig
    state = get_state()
    if os.path.exists(state.memory_config_yaml):
        return MemoryConfig.from_yaml(state.memory_config_yaml)
    return MemoryConfig()


@router.get("/api/memory")
def get_memory_config():
    cfg = _load_memory_config()
    return {
        "short_term": {
            "enabled":               cfg.short_term.enabled,
            "max_turns":             cfg.short_term.max_turns,
            "max_tokens":            cfg.short_term.max_tokens,
            "distill_enabled":       cfg.short_term.distill_enabled,
            "distill_trigger_steps": cfg.short_term.distill_trigger_steps,
            "max_distillate_tokens": cfg.short_term.max_distillate_tokens,
        },
        "medium_term": {
            "enabled":                   cfg.medium_term.enabled,
            "window_days":               cfg.medium_term.window_days,
            "max_entries":               cfg.medium_term.max_entries,
            "max_chars":                 cfg.medium_term.max_chars,
            "consolidate_enabled":       cfg.medium_term.consolidate_enabled,
            "consolidate_batch":         cfg.medium_term.consolidate_batch,
            "consolidate_interval_days": cfg.medium_term.consolidate_interval_days,
            "max_consolidate_tokens":    cfg.medium_term.max_consolidate_tokens,
        },
        "long_term": {
            "enabled":            cfg.long_term.enabled,
            "top_k":              cfg.long_term.top_k,
            "max_recall_chars":   cfg.long_term.max_recall_chars,
            "consolidation_k":    cfg.long_term.consolidation_k,
            "distill_enabled":    cfg.long_term.distill_enabled,
            "max_distill_tokens": cfg.long_term.max_distill_tokens,
        },
        "milestone": {
            "enabled":              cfg.milestone.enabled,
            "max_milestones":       cfg.milestone.max_milestones,
            "importance_threshold": cfg.milestone.importance_threshold,
            "top_k_retrieve":       cfg.milestone.top_k_retrieve,
            "inject_detail":        cfg.milestone.inject_detail,
        },
    }


@router.post("/api/memory/save")
def save_memory_config(req: MemorySaveRequest):
    import yaml
    state = get_state()
    path = state.memory_config_yaml
    existing: dict = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    existing["short_term"] = {
        **existing.get("short_term", {}),
        "enabled":               req.st_enabled,
        "max_turns":             req.st_max_turns,
        "max_tokens":            req.st_max_tokens,
        "distill_enabled":       req.st_distill_enabled,
        "distill_trigger_steps": req.st_distill_trigger_steps,
        "max_distillate_tokens": req.st_max_distillate_tokens,
    }
    existing["medium_term"] = {
        **existing.get("medium_term", {}),
        "enabled":                   req.mt_enabled,
        "window_days":               req.mt_window_days,
        "max_entries":               req.mt_max_entries,
        "max_chars":                 req.mt_max_chars,
        "consolidate_enabled":       req.mt_consolidate_enabled,
        "consolidate_batch":         req.mt_consolidate_batch,
        "consolidate_interval_days": req.mt_consolidate_interval_days,
        "max_consolidate_tokens":    req.mt_max_consolidate_tokens,
    }
    existing["long_term"] = {
        **existing.get("long_term", {}),
        "enabled":            req.lt_enabled,
        "top_k":              req.lt_top_k,
        "max_recall_chars":   req.lt_max_recall_chars,
        "consolidation_k":    req.lt_consolidation_k,
        "distill_enabled":    req.lt_distill_enabled,
        "max_distill_tokens": req.lt_max_distill_tokens,
    }
    existing["milestone"] = {
        **existing.get("milestone", {}),
        "enabled":              req.ms_enabled,
        "max_milestones":       req.ms_max_milestones,
        "importance_threshold": req.ms_importance_threshold,
        "top_k_retrieve":       req.ms_top_k_retrieve,
        "inject_detail":        req.ms_inject_detail,
    }

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
    return {"status": "ok"}


@router.post("/api/memory/consolidate")
def consolidate_medium_term():
    state = get_state()
    if state.conv_loop is None:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detail": "No active session."},
        )
    medium = getattr(state.conv_loop._tao, "_medium_term", None)
    if medium is None:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detail": "Medium-term memory not enabled."},
        )
    did = medium.consolidate(force=True)
    if did:
        return {"status": "ok", "message": "Consolidation completed."}
    return {"status": "ok", "message": "Nothing to consolidate."}
