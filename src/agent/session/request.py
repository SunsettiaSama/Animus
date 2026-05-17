from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TaoRequest:
    """统一请求信封。每个请求携带 kind 标记，由 SessionManager 分发到目标会话。

    kind:
        user        — 用户对话轮次，走 ConvLoop.stream()
        heartbeat   — 调度心跳检查（预留，暂由 HeartbeatModule 处理）
        soul_tick   — 灵魂心跳：自主内在思考（后续扩展）
    """

    kind: Literal["user", "heartbeat", "soul_tick"]
    session_id: str
    question: str = ""
    payload: dict = field(default_factory=dict)
    gen_id: str = ""
    stream_mode: str = "flush"
