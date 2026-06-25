from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.soul.speak.llm.engine import SpeakLLMEngine

if TYPE_CHECKING:
    from agent.soul.memory.io.session import DialogueCompressionBlock

from .chunk_types import DialogueContextChunk
from .render import (
    normalize_one_sentence,
    render_dialogue_compressed,
    render_dialogue_context_for_prompt,
    render_recent_turns_for_prompt,
    render_session_working_memory,
)

DistillFn = Callable[[list[tuple[str, str]], list[str]], str]

_DISTILL_SYSTEM = (
    "你是会话上下文压缩器。"
    "请根据给定的对话原文，以及此前已压缩的单句摘要（若有），"
    "将本轮待压缩的对话蒸馏为恰好一句话。"
    "人称：Agent 用第二人称「你」；尽量客观转述已出现的事实与意图，"
    "句末可点一句你当下的轻微感受；不添加未出现的信息（不加戏）。"
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
        self._agent_persona_provider: Callable[[], str] | None = None
        self._resolve_interactor: Callable[[str], str] | None = None

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

    def set_agent_persona_provider(self, provider: Callable[[], str] | None) -> None:
        self._agent_persona_provider = provider

    def set_resolve_interactor(self, resolver: Callable[[str], str] | None) -> None:
        self._resolve_interactor = resolver

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
        """记账：仅累积 chunk，蒸馏由导演 distill_if_requested 触发。"""
        self.record_chunk(session_id, user_text, agent_text)

    def record_chunk(
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

    def distill_if_requested(self, session_id: str) -> bool:
        """导演显式请求时启动排队蒸馏。"""
        state = self._session(session_id)
        should_pump = False
        with state.lock:
            should_pump = bool(state.queued_batches) and not state.distilling
            if should_pump:
                state.distilling = True
        if should_pump:
            self._submit(lambda sid=session_id: self._pump_session(sid))
            return True
        return False

    def prompt_block(self, session_id: str) -> str:
        """非阻塞：已完成蒸馏摘要（无 prompt 头，供 compose / 决策）。"""
        state = self._sessions.get(session_id)
        if state is None:
            return ""
        with state.lock:
            return render_dialogue_compressed(list(state.distilled))

    def context_distill_block(self, session_id: str) -> str:
        """非阻塞：主接口 system 用上下文蒸馏块（含预置框）。"""
        state = self._sessions.get(session_id)
        if state is None:
            return ""
        with state.lock:
            return render_dialogue_context_for_prompt(list(state.distilled))

    def working_memory_block(self, session_id: str, *, generation: int) -> str:
        """非阻塞：主接口 system 用工作记忆（仅未蒸馏的最近轮次原文）。"""
        state = self._sessions.get(session_id)
        if state is None:
            return ""
        with state.lock:
            recent_turns = [
                (chunk.user_text, chunk.agent_text) for chunk in state.buffer
            ]
        return render_recent_turns_for_prompt(
            generation=generation,
            recent_turns=recent_turns,
        )

    def session_context_blocks(self, session_id: str, *, generation: int) -> tuple[str, str]:
        """(上下文蒸馏块, 工作记忆块)。"""
        return (
            self.context_distill_block(session_id),
            self.working_memory_block(session_id, generation=generation),
        )

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
                "buffer_chunks": [
                    {"user": c.user_text, "agent": c.agent_text}
                    for c in state.buffer
                ],
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
        from agent.soul.speak.pipelines.request_driven.orchestrator.prompt_trace import get_prompt_trace
        from .structured_distill import _SCHEMA_HINT, _render_transcript, _structured_system

        trace = get_prompt_trace()
        trace_enabled = trace.is_enabled(session_id)
        distill_user = ""
        if trace_enabled:
            distill_user_lines: list[str] = []
            if prior:
                distill_user_lines.append("此前压缩摘要：")
                distill_user_lines.extend(f"- {line}" for line in prior)
            distill_user_lines.append(f"待压缩的最近 {len(batch)} 轮对话：")
            distill_user_lines.append(_render_transcript(batch))
            distill_user_lines.append(f"\n输出 schema：\n{_SCHEMA_HINT}")
            distill_user = "\n".join(distill_user_lines)

        persona = ""
        if self._agent_persona_provider is not None:
            persona = self._agent_persona_provider().strip()
        interactor_id = ""
        if self._resolve_interactor is not None:
            interactor_id = (self._resolve_interactor(session_id) or "").strip()
        block = distill_compression_block(
            self._llm,
            session_id=session_id,
            block_index=block_index,
            batch=batch,
            prior=prior,
            agent_persona_narrative=persona,
            interactor_id=interactor_id,
        )
        sentence = normalize_one_sentence(block.summary)

        if trace_enabled:
            trace.emit_submodule_llm(
                session_id,
                submodule="distiller.compression",
                system=_structured_system(persona),
                user=distill_user,
                response_preview=block.summary,
            )

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
                lines.append(f"{index}. 你：{chunk.agent_text}")
        user_prompt = "\n".join(lines)
        result = self._llm.generate(user_prompt, system=_DISTILL_SYSTEM)
        return result.text


def _default_submit(task: Callable[[], None]) -> None:
    thread = threading.Thread(target=task, daemon=True)
    thread.start()
