"""history 路由 — 只读存档（single-stream Phase 4）。

轮次历史已退役（需求 R1）：转录不再写入/删除，记忆系统是唯一的历史
（/api/memory/timeline）。本路由仅保留 GET 供旧存档浏览与诊断；
写端点已移除，js2 侧 history_store 已停写。
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from state import get_state
from webui.history_files import resolve_history_path

router = APIRouter()


@router.get("/api/history")
def list_history():
    state = get_state()
    if not os.path.isdir(state.history_dir):
        return {"conversations": []}
    convs = []
    for fn in sorted(os.listdir(state.history_dir), reverse=True):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(state.history_dir, fn)
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        convs.append({
            "id":         c.get("id", fn[:-5]),
            "title":      c.get("title", "Untitled"),
            "mode":       c.get("mode", "chat"),
            "session_id": c.get("session_id", ""),
            "channel_id": c.get("channel_id", ""),
            "agent_initiated": bool(c.get("agent_initiated", False)),
            "proactive_unread": bool(c.get("proactive_unread", c.get("agent_initiated", False))),
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
        })
    return {"conversations": convs}


@router.get("/api/history/{conv_id}")
def get_history_item(conv_id: str):
    state = get_state()
    path = resolve_history_path(state.history_dir, conv_id)
    if not path:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    with open(path, encoding="utf-8") as f:
        return json.load(f)
