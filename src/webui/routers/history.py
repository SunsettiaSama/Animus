from __future__ import annotations

import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


class SaveConvRequest(BaseModel):
    id: str
    title: str
    mode: str
    messages: list
    created_at: str
    updated_at: str


@router.get("/api/history")
def list_history():
    state = get_state()
    os.makedirs(state.history_dir, exist_ok=True)
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
            "updated_at": c.get("updated_at", ""),
        })
    return {"conversations": convs}


@router.get("/api/history/{conv_id}")
def get_history_item(conv_id: str):
    state = get_state()
    path = os.path.join(state.history_dir, f"{conv_id}.json")
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "Not found"})
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@router.post("/api/history")
def save_history_item(req: SaveConvRequest):
    state = get_state()
    os.makedirs(state.history_dir, exist_ok=True)
    path = os.path.join(state.history_dir, f"{req.id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(req.dict(), f, ensure_ascii=False, indent=2)
    return {"status": "ok"}


@router.post("/api/history/{conv_id}")
def save_history_item_by_id(req: SaveConvRequest, conv_id: str):
    state = get_state()
    os.makedirs(state.history_dir, exist_ok=True)
    path = os.path.join(state.history_dir, f"{conv_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(req.dict(), f, ensure_ascii=False, indent=2)
    return {"status": "ok"}


@router.delete("/api/history/{conv_id}")
def delete_history_item(conv_id: str):
    state = get_state()
    path = os.path.join(state.history_dir, f"{conv_id}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "ok"}


@router.delete("/api/history")
def clear_all_history():
    state = get_state()
    if not os.path.exists(state.history_dir):
        return {"status": "ok", "deleted": 0}
    count = 0
    for fn in os.listdir(state.history_dir):
        if fn.endswith(".json"):
            os.remove(os.path.join(state.history_dir, fn))
            count += 1
    return {"status": "ok", "deleted": count}
