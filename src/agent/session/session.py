from __future__ import annotations

import logging
import queue as _queue
import threading
from typing import Any, Callable

from .request import TaoRequest

logger = logging.getLogger(__name__)

_STOP = object()


class AgentSession:
    """独立会话单元：持有一个 ConvLoop 和专属 worker 线程。

    每个会话顺序处理自己队列中的请求（同一会话内串行），
    不同会话之间并发运行（由 SessionManager 保证）。
    """

    def __init__(
        self,
        session_id: str,
        conv_loop: Any,
        notify_fn: Callable[[str, str, bool], None] | None = None,
    ) -> None:
        self._id = session_id
        self._conv_loop = conv_loop
        self._notify_fn = notify_fn
        self._req_q: _queue.Queue = _queue.Queue()
        self._thread = threading.Thread(
            target=self._worker,
            name=f"tao-{session_id}",
            daemon=True,
        )
        self._thread.start()
        tao = getattr(conv_loop, "tao_loop", None)
        if tao is not None and hasattr(tao, "set_life_interaction_session"):
            tao.set_life_interaction_session(session_id)
        logger.info("[AgentSession] %r started", session_id)

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._id

    @property
    def conv_loop(self) -> Any:
        return self._conv_loop

    def submit(self, req: TaoRequest) -> _queue.Queue:
        """把请求压入队列，返回响应 Queue（调用方轮询或阻塞读取，None 表示流结束）。"""
        resp_q: _queue.Queue = _queue.Queue()
        self._req_q.put((req, resp_q))
        return resp_q

    def abort(self) -> None:
        self._conv_loop.abort()

    def resolve_approval(self, request_id: str, approved: bool) -> bool:
        return self._conv_loop.resolve_approval(request_id, approved)

    def restore(self, messages: list[dict]) -> None:
        self._conv_loop.restore(messages)

    def reset(self) -> None:
        """清空对话历史并闭合当前 Anchor 交互会话（内化入 life-worker）。"""
        self._conv_loop.reset()

    def close(self) -> None:
        self._req_q.put(_STOP)
        self._thread.join(timeout=15.0)
        tao = getattr(self._conv_loop, "tao_loop", self._conv_loop)
        if hasattr(tao, "close"):
            tao.close()
        logger.info("[AgentSession] %r closed", self._id)

    # ── Worker ─────────────────────────────────────────────────────────────────

    def _worker(self) -> None:
        while True:
            item = self._req_q.get()
            if item is _STOP:
                break
            req, resp_q = item
            try:
                if req.kind == "user":
                    self._handle_user(req, resp_q)
                else:
                    resp_q.put({"type": "error", "message": f"Unsupported kind: {req.kind}"})
            except Exception as exc:
                logger.exception("[AgentSession] %r unhandled error: %s", self._id, exc)
                resp_q.put({"type": "error", "message": str(exc)})
            finally:
                resp_q.put(None)  # 流结束哨兵

    def _handle_user(self, req: TaoRequest, resp_q: _queue.Queue) -> None:
        from agent.adapters.react_stream import composer_for_mode
        from agent.adapters.react_wire import wire_sink_for_sub_agent

        composer = composer_for_mode(req.stream_mode)
        sink = wire_sink_for_sub_agent(resp_q.put)
        self._conv_loop.set_sub_event_sink(sink)

        try:
            for msg in composer.iter_dialog_messages(
                self._conv_loop.stream(req.question)
            ):
                resp_q.put(msg)
        finally:
            self._conv_loop.set_sub_event_sink(None)

        was_aborted = self._conv_loop.abort_signaled
        if was_aborted:
            self._conv_loop.rollback_unfinished_turn()
            resp_q.put({"type": "finish", "answer": "", "aborted": True})
        else:
            self._run_post_process()

    def _run_post_process(self) -> None:
        if self._notify_fn:
            self._notify_fn("post_process", "正在写入记忆…", False)
        self._conv_loop.post_process()
        if self._notify_fn:
            self._notify_fn("post_process", "记忆写入完成", True)
