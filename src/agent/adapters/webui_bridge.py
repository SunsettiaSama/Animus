"""WebUI 专用中间层：在 FastAPI 路由与 SessionManager 之间提供一层语义隔离。

职责
----
- 持有 WebUI 默认会话的 session_id 常量
- 提供 is_ready() / get_session() / get_status() 等状态查询
- stream_user_turn() 将同步响应 Queue 桥接为 async 迭代器，供 WebSocket/SSE 路由使用
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from agent.session.request import TaoRequest

if TYPE_CHECKING:
    from agent.session.session import AgentSession

logger = logging.getLogger(__name__)

WEBUI_SESSION_ID = "webui"


class WebUIBridge:
    """将 WebUI HTTP/WS 请求转发到 SessionManager 的 webui 会话。"""

    def __init__(self, state: Any) -> None:
        self._state = state

    # ── Status ────────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        mgr = self._state.session_manager
        return mgr is not None and mgr.get(WEBUI_SESSION_ID) is not None

    def get_session(self) -> AgentSession | None:
        mgr = self._state.session_manager
        return mgr.get(WEBUI_SESSION_ID) if mgr is not None else None

    def get_status(self) -> dict:
        if self._state.react_init_error:
            return {"status": "error", "detail": self._state.react_init_error}
        if not self.is_ready():
            if not self._state.react_init_event.is_set():
                return {"status": "initializing"}
            return {"status": "not_initialized"}
        return {"status": "ready", "is_streaming": self._state.is_streaming}

    # ── Streaming ─────────────────────────────────────────────────────────────

    async def stream_user_turn(
        self,
        question: str,
        gen_id: str,
        stream_mode: str = "flush",
    ) -> AsyncIterator[dict]:
        """提交用户轮次请求，将同步 Queue 桥接为 async 迭代器。

        内部用 asyncio.to_thread 阻塞等待每条消息，保持事件循环不阻塞。
        调用方通过 async for 消费，遇到 None 哨兵自动停止。
        """
        mgr = self._state.session_manager
        if mgr is None:
            yield {"type": "error", "message": "SessionManager not initialized."}
            return

        req = TaoRequest(
            kind="user",
            session_id=WEBUI_SESSION_ID,
            question=question,
            gen_id=gen_id,
            stream_mode=stream_mode,
        )
        resp_q = mgr.submit(req)
        if resp_q is None:
            yield {"type": "error", "message": "Session not initialized."}
            return

        while True:
            item = await asyncio.to_thread(resp_q.get)
            if item is None:
                break
            yield item
