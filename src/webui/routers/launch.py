"""launch router — 薄适配：HTTP ↔ launch 层（判定正本在 src/launch/status.py）。"""
from __future__ import annotations

from fastapi import APIRouter

from launch.status import snapshot
from state import get_state

router = APIRouter()


@router.get("/api/launch/status")
def get_launch_status():
    """启动站五阶段聚合状态（供 hub 页轮询）。纯读，永不 500。"""
    return snapshot(get_state())
