from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReactActionCall:
    action: str
    action_args: dict[str, Any]


def parse_action_field(payload: dict[str, Any]) -> ReactActionCall | None:
    """从 agent 步输出解析追加字段 ``action: {action, action_args}``。"""
    raw = payload.get("action")
    if raw is None:
        return None
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            return None
        return ReactActionCall(action=name, action_args={})
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("action", "")).strip()
    if not name:
        return None
    args = raw.get("action_args")
    if args is None:
        args = raw.get("acion_args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        args = {"value": args}
    return ReactActionCall(action=name, action_args=dict(args))
