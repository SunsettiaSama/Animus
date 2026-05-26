from __future__ import annotations

from typing import Any


def build_anchor_request(tool_name: str) -> dict[str, Any]:
    """现实锚点工具占位：向外传递请求结构，暂不调用 Tao。"""
    name = tool_name.strip()
    return {
        "ok": False,
        "implemented": False,
        "tool": name,
        "reason": "现实锚点工具暂未实现",
    }
