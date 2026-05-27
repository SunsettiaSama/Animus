from __future__ import annotations

from typing import Any

# 备忘录 — 现实扰动 [anchor:...] 接入点（当前关闭）
#
# 顶层工具处理层完成后，在此将 anchor 请求转为抽象 text 任务，
# 交由 ReAct 等循环执行；该层目标是追求极致的任务完成效率。
#
# 接线位置：
# - compose/system/output_format.py：恢复 [anchor:工具名] 输出说明
# - speak/service.run_turn：解析 anchor_tool → build_anchor_request → 调度工具层
# - speak/handler：向外暴露 anchor_request（或任务结果）

ANCHOR_ENABLED = False


def build_anchor_request(tool_name: str) -> dict[str, Any]:
    """现实锚点工具占位：顶层工具处理层接入前不进入 speak 逻辑。"""
    name = tool_name.strip()
    if not ANCHOR_ENABLED:
        return {
            "ok": False,
            "implemented": False,
            "tool": name,
            "reason": "现实扰动暂未启用，等待工具处理层接入",
        }
    return {
        "ok": False,
        "implemented": False,
        "tool": name,
        "reason": "现实锚点工具暂未实现",
    }
