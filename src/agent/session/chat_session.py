"""ChatSession — 轻量闲聊会话，无 ReAct 工具链，仅做多轮 LLM 对话。

职责
----
- 持有对话历史（滚动窗口）
- 接受可配置 system_prompt（后续可注入 persona / 情绪 / life profile）
- 通过专属 worker 线程串行处理请求，与 AgentSession 接口一致
- 流式输出与 AgentSession 相同的 wire dict（type: chunk / finish / error）

后续扩展接口
-----------
- set_system_prompt(text)  — 动态更新 system prompt（灵魂心跳可用此接口注入状态）
- inject_context(text)     — 在本轮追加一条临时 context block（不入 history）
"""
from __future__ import annotations

import logging
import queue as _queue
import threading
from typing import Any

from .request import TaoRequest

logger = logging.getLogger(__name__)

_STOP = object()

_DEFAULT_SYSTEM = (
    "你是一个友好、真诚的 AI 助手。请用自然、流畅的语言与用户闲聊，"
    "不需要使用工具，直接回答即可。"
)


class ChatSession:
    """轻量闲聊会话：LLM + 历史 + worker 线程。

    接口与 AgentSession 保持一致，可直接注册到 SessionManager。
    """

    def __init__(
        self,
        session_id: str,
        llm: Any,
        system_prompt: str = _DEFAULT_SYSTEM,
        max_history_turns: int = 20,
    ) -> None:
        self._id = session_id
        self._llm = llm
        self._system_prompt = system_prompt
        self._max_history = max_history_turns
        self._history: list[dict] = []          # [{"role": "user"|"assistant", "content": str}]
        self._pending_context: str = ""         # 本轮注入的临时上下文（用后清空）
        self._stop_event = threading.Event()
        self._req_q: _queue.Queue = _queue.Queue()
        self._thread = threading.Thread(
            target=self._worker,
            name=f"chat-{session_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("[ChatSession] %r started", session_id)

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._id

    def submit(self, req: TaoRequest) -> _queue.Queue:
        """压入请求，返回响应 Queue（None 哨兵表示流结束）。"""
        resp_q: _queue.Queue = _queue.Queue()
        self._req_q.put((req, resp_q))
        return resp_q

    def abort(self) -> None:
        self._stop_event.set()

    def reset(self) -> None:
        self._history.clear()
        self._pending_context = ""
        logger.debug("[ChatSession] %r history cleared", self._id)

    def set_system_prompt(self, text: str) -> None:
        """动态更新 system prompt，立即对下一轮生效。"""
        self._system_prompt = text

    def inject_context(self, text: str) -> None:
        """注入仅本轮生效的临时上下文（不写入 history）。用于心跳状态注入。"""
        self._pending_context = text

    def close(self) -> None:
        self._req_q.put(_STOP)
        self._thread.join(timeout=10.0)
        logger.info("[ChatSession] %r closed", self._id)

    # ── Worker ─────────────────────────────────────────────────────────────────

    def _worker(self) -> None:
        while True:
            item = self._req_q.get()
            if item is _STOP:
                break
            req, resp_q = item
            self._stop_event.clear()
            try:
                self._handle_chat(req, resp_q)
            except Exception as exc:
                logger.exception("[ChatSession] %r error: %s", self._id, exc)
                resp_q.put({"type": "error", "message": str(exc)})
            finally:
                resp_q.put(None)

    def _handle_chat(self, req: TaoRequest, resp_q: _queue.Queue) -> None:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        # ── 组装 messages ──────────────────────────────────────────────────────
        messages = []

        system_parts = [self._system_prompt]
        if self._pending_context:
            system_parts.append(f"\n\n[当前状态参考]\n{self._pending_context}")
            self._pending_context = ""
        messages.append(SystemMessage(content="\n".join(filter(None, system_parts))))

        for turn in self._history[-self._max_history * 2:]:
            if turn["role"] == "user":
                messages.append(HumanMessage(content=turn["content"]))
            else:
                messages.append(AIMessage(content=turn["content"]))

        messages.append(HumanMessage(content=req.question))

        # ── 流式生成 ───────────────────────────────────────────────────────────
        full_response = ""
        for chunk in self._llm.stream_generate_messages(messages):
            if self._stop_event.is_set():
                resp_q.put({"type": "finish", "answer": full_response, "aborted": True})
                return
            resp_q.put({"type": "chunk", "chunk": chunk})
            full_response += chunk

        # ── 更新历史 ───────────────────────────────────────────────────────────
        self._history.append({"role": "user", "content": req.question})
        self._history.append({"role": "assistant", "content": full_response})

        # 超出窗口时从头截断（保留整数对）
        if len(self._history) > self._max_history * 2:
            self._history = self._history[-(self._max_history * 2):]

        resp_q.put({"type": "finish", "answer": full_response})
