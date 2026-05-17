"""ReAct HTTP/WS：对话串流输出的抽象接口与两类实现（chunk 增量 / flush 逐步）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Iterable, Iterator


class ReactOutputMode(str, Enum):
    """对线协议：`chunk`=分片吐出；`flush`=同一 LLM 步内的 token 聚合后再出一条。"""

    CHUNK_STREAM = "chunk"
    STEP_FLUSH = "flush"


_LEGACY_MODES: dict[str, ReactOutputMode] = {
    ReactOutputMode.CHUNK_STREAM.value: ReactOutputMode.CHUNK_STREAM,
    "live": ReactOutputMode.CHUNK_STREAM,
    ReactOutputMode.STEP_FLUSH.value: ReactOutputMode.STEP_FLUSH,
    "batched": ReactOutputMode.STEP_FLUSH,
}


def coerce_output_mode(raw: str | ReactOutputMode) -> ReactOutputMode:
    if isinstance(raw, ReactOutputMode):
        return raw
    key = raw.strip().lower()
    return _LEGACY_MODES.get(key, ReactOutputMode.CHUNK_STREAM)


class ConversationWireComposer(ABC):
    """将 Tao 原始事件适配为带 ``channel`` 的线字典（不含 Flow；Flow 单独 fan-out）。"""

    @abstractmethod
    def iter_dialog_messages(self, tao_events: Iterable[Any]) -> Iterator[dict]:
        ...


class ChunkStreamComposer(ConversationWireComposer):
    """增量 chunk：与同一步内高频 flush（``live_flush_n`` 阈值）。"""

    def __init__(self, *, live_flush_n: int = 4) -> None:
        self._live_flush_n = live_flush_n

    def iter_dialog_messages(self, tao_events: Iterable[Any]) -> Iterator[dict]:
        from agent.adapters.react_wire import (
            envelope_dialog_wire,
            tao_event_to_wire_dict,
        )
        from agent.react.tao import ChunkEvent

        chunk_buf: list[str] = []
        chunk_idx: int = -1

        def _flush_chunks() -> dict | None:
            nonlocal chunk_buf, chunk_idx
            if not chunk_buf:
                return None
            msg = envelope_dialog_wire(
                {"type": "chunk", "index": chunk_idx, "chunk": "".join(chunk_buf)}
            )
            chunk_buf = []
            chunk_idx = -1
            return msg

        for event in tao_events:
            if isinstance(event, ChunkEvent):
                if event.index != chunk_idx:
                    flushed = _flush_chunks()
                    if flushed is not None:
                        yield flushed
                    chunk_idx = event.index
                chunk_buf.append(event.chunk)
                if len(chunk_buf) >= self._live_flush_n:
                    flushed = _flush_chunks()
                    if flushed is not None:
                        yield flushed
            else:
                flushed = _flush_chunks()
                if flushed is not None:
                    yield flushed
                msg = tao_event_to_wire_dict(event)
                if msg is not None:
                    yield envelope_dialog_wire(msg)
        flushed = _flush_chunks()
        if flushed is not None:
            yield flushed


class StepFlushComposer(ConversationWireComposer):
    """Flush 步：仅在非 Chunk 边界聚合本步的全部 token。"""

    def iter_dialog_messages(self, tao_events: Iterable[Any]) -> Iterator[dict]:
        from agent.adapters.react_wire import (
            envelope_dialog_wire,
            tao_event_to_wire_dict,
        )
        from agent.react.tao import ChunkEvent

        chunk_buf: list[str] = []
        chunk_idx: int = -1

        def _flush_chunks() -> dict | None:
            nonlocal chunk_buf, chunk_idx
            if not chunk_buf:
                return None
            msg = envelope_dialog_wire(
                {"type": "chunk", "index": chunk_idx, "chunk": "".join(chunk_buf)}
            )
            chunk_buf = []
            chunk_idx = -1
            return msg

        for event in tao_events:
            if isinstance(event, ChunkEvent):
                if event.index != chunk_idx:
                    flushed = _flush_chunks()
                    if flushed is not None:
                        yield flushed
                    chunk_idx = event.index
                chunk_buf.append(event.chunk)
            else:
                flushed = _flush_chunks()
                if flushed is not None:
                    yield flushed
                msg = tao_event_to_wire_dict(event)
                if msg is not None:
                    yield envelope_dialog_wire(msg)
        flushed = _flush_chunks()
        if flushed is not None:
            yield flushed


def composer_for_mode(mode: ReactOutputMode | str, *, live_flush_n: int = 4) -> ConversationWireComposer:
    m = coerce_output_mode(mode)
    if m == ReactOutputMode.STEP_FLUSH:
        return StepFlushComposer()
    return ChunkStreamComposer(live_flush_n=live_flush_n)
