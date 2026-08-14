from __future__ import annotations

from typing import Literal

# clear：场子干净 / 用户刚开口
# typing：打字机吐字消费中
# awaiting_user：agent 说完，用户尚未回复（含刚说完与沉默延续，体感看 idle）
FloorPhase = Literal["clear", "typing", "awaiting_user"]


def floor_nl(phase: FloorPhase, *, idle_ms: int = 0) -> str:
    if phase == "typing":
        return (
            "台面状态：agent 台词正在打字机吐字消费中，话还没说完。"
            "这一拍避免再开新口。"
        )
    if phase == "awaiting_user":
        sec = max(0.0, idle_ms / 1000.0)
        return (
            "台面状态：agent 已说完，用户尚未回复"
            f"（空闲约 {sec:.1f} 秒，仅供体感）。"
            "刚说完可以先听；沉默拉开后，按对话弧与待分享决定要不要轻声补一句，避免复读同一句。"
        )
    return "台面状态：场子干净，按本拍 trigger 与对话弧判断即可。"
