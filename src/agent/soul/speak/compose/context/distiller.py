from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from agent.soul.memory.session.types import DialogueCompressionBlock
from agent.soul.speak.llm.engine import SpeakLLMEngine

from .chunk_types import DialogueContextChunk
from .render import normalize_one_sentence, render_dialogue_compressed

DistillFn = Callable[[list[tuple[str, str]], list[str]], str]

_DISTILL_SYSTEM = (
    "你是会话上下文压缩器。"
    "请根据给定的对话原文，以及此前已压缩的单句摘要（若有），"
    "将本轮待压缩的对话蒸馏为恰好一句话。"
    "忠实转述已出现的事实与意图，不添加情绪、评价或未出现的信息（不加戏）。"
    "只输出这一句话：不要编号、不要列表、不要引号、不要换行、不要解释。"
)


@dataclass
class _SessionDistillState:
    distilled: list[str] = field(default_factory=list)
    buffer: list[DialogueContextChunk] = field(default_factory=list)
    queued_batches: list[list[DialogueContextChunk]] = field(default_factory=list)
    distilling: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class SpeakContextDistiller:
    """当前会话上下文蒸馏：每 k 个 chunk 异步压缩为一句，compose 时非阻塞读取。"""

    def __init__(
        self,
        *,
        llm_engine: SpeakLLMEngine | None = None,
        chunk_size: int = 4,
        distill_fn: DistillFn | None = None,
        submit: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size 必须 >= 1")
        self._llm = llm_engine
        self._chunk_size = chunk_size
        self._distill_fn = distill_fn
        self._submit = submit or _default_submit
        self._sessions: dict[str, _SessionDistillState] = {}
        self._on_block_ready: Callable[[DialogueCompressionBlock], None] | None = None

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    def set_llm_engine(self, llm: SpeakLLMEngine | None) -> None:
        self._llm = llm

    def set_on_block_ready(
        self,
        handler: Callable[[DialogueCompressionBlock], None] | None,
    ) -> None:
        self._on_block_ready = handler

    def reset_session(self, session_id: str) -> None:
        state = self._sessions.pop(session_id, None)
        if state is None:
            return
        with state.lock:
            state.distilled.clear()
            state.buffer.clear()
            state.queued_batches.clear()
            state.distilling = False

    def on_turn(
        self,
        session_id: str,
        user_text: str,
        agent_text: str,
    ) -> None:
        user = user_text.strip()
        agent = agent_text.strip()
        if not user and not agent:
            return

        state = self._session(session_id)
        with state.lock:
            state.buffer.append(DialogueContextChunk(user_text=user, agent_text=agent))
            while len(state.buffer) >= self._chunk_size:
                batch = state.buffer[: self._chunk_size]
                state.buffer = state.buffer[self._chunk_size :]
                state.queued_batches.append(batch)
            should_pump = bool(state.queued_batches) and not state.distilling
            if should_pump:
                state.distilling = True
        if should_pump:
            self._submit(lambda sid=session_id: self._pump_session(sid))

    def prompt_block(self, session_id: str) -> str:
        """非阻塞：仅返回已完成蒸馏的单句摘要。"""
        state = self._sessions.get(session_id)
        if state is None:
            return ""
        with state.lock:
            return render_dialogue_compressed(list(state.distilled))

    def snapshot(self, session_id: str) -> dict[str, object]:
        state = self._sessions.get(session_id)
        if state is None:
            return {
                "session_id": session_id,
                "distilled_count": 0,
                "buffer_count": 0,
                "pending_jobs": 0,
                "distilling": False,
            }
        with state.lock:
            return {
                "session_id": session_id,
                "distilled_count": len(state.distilled),
                "buffer_count": len(state.buffer),
                "pending_jobs": len(state.queued_batches),
                "distilling": state.distilling,
                "distilled": list(state.distilled),
            }

    def _session(self, session_id: str) -> _SessionDistillState:
        state = self._sessions.get(session_id)
        if state is None:
            state = _SessionDistillState()
            self._sessions[session_id] = state
        return state

    def _pump_session(self, session_id: str) -> None:
        state = self._session(session_id)
        with state.lock:
            if not state.queued_batches:
                state.distilling = False
                return
            batch = state.queued_batches.pop(0)
            prior = list(state.distilled)

        from .structured_distill import distill_compression_block

        block_index = len(prior)
        block = distill_compression_block(
            self._llm,
            session_id=session_id,
            block_index=block_index,
            batch=batch,
            prior=prior,
        )
        sentence = normalize_one_sentence(block.summary)

        with state.lock:
            if sentence:
                state.distilled.append(sentence)
            if state.queued_batches:
                self._submit(lambda sid=session_id: self._pump_session(sid))
            else:
                state.distilling = False

        if block.summary.strip() and self._on_block_ready is not None:
            self._on_block_ready(block)

    def _distill_batch(
        self,
        batch: list[DialogueContextChunk],
        prior: list[str],
    ) -> str:
        if self._distill_fn is not None:
            return self._distill_fn(
                [(chunk.user_text, chunk.agent_text) for chunk in batch],
                prior,
            )
        if self._llm is None:
            return ""
        lines: list[str] = []
        if prior:
            lines.append("此前压缩摘要：")
            lines.extend(f"- {line}" for line in prior)
        lines.append(f"待压缩的最近 {len(batch)} 轮对话：")
        for index, chunk in enumerate(batch, start=1):
            if chunk.user_text:
                lines.append(f"{index}. 用户：{chunk.user_text}")
            if chunk.agent_text:
                lines.append(f"{index}. 我：{chunk.agent_text}")
        user_prompt = "\n".join(lines)
        result = self._llm.generate(user_prompt, system=_DISTILL_SYSTEM)
        return result.text


def _default_submit(task: Callable[[], None]) -> None:
    thread = threading.Thread(target=task, daemon=True)
    thread.start()
