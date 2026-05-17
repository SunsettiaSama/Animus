from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from .request import TaoRequest
from .session import AgentSession

logger = logging.getLogger(__name__)


class SessionManager:
    """多会话注册表：每个 session_id 对应一个独立的 AgentSession。

    并发模型：不同会话并发运行（各自有专属 worker 线程）；
              同一会话内请求串行（FIFO 队列）。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()

    # ── Session lifecycle ──────────────────────────────────────────────────────

    def create_session(
        self,
        session_id: str,
        conv_loop: Any,
        notify_fn: Callable[[str, str, bool], None] | None = None,
        replace: bool = True,
    ) -> AgentSession:
        """从 ConvLoop 构建 AgentSession 并注册。replace=True 时先关闭旧会话。"""
        session = AgentSession(session_id, conv_loop, notify_fn=notify_fn)
        self.register(session_id, session, replace=replace)
        return session

    def register(self, session_id: str, session: Any, replace: bool = True) -> Any:
        """直接注册一个已构建好的 session 对象（鸭子类型：需有 submit / abort / close）。

        供 ChatSession 等非 AgentSession 类型使用。
        """
        with self._lock:
            if session_id in self._sessions:
                if not replace:
                    return self._sessions[session_id]
                old = self._sessions.pop(session_id)
                old.close()
            self._sessions[session_id] = session
        logger.info("[SessionManager] session registered: %r  active=%d", session_id, len(self._sessions))
        return session

    def get(self, session_id: str) -> AgentSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def destroy(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()
            logger.info("[SessionManager] session destroyed: %r  active=%d", session_id, len(self._sessions))

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.close()
        logger.info("[SessionManager] all sessions stopped")

    # ── Request submission ─────────────────────────────────────────────────────

    def submit(self, req: TaoRequest) -> "queue.Queue | None":
        """提交请求到目标会话，返回响应 Queue；会话不存在时返回 None。"""
        import queue
        session = self.get(req.session_id)
        if session is None:
            logger.warning("[SessionManager] submit: session %r not found", req.session_id)
            return None
        return session.submit(req)

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def active_sessions(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
