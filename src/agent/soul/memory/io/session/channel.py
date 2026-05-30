from __future__ import annotations

from collections.abc import Callable

from .buffer import SessionMemoryBuffer
from .request import (
    CompressionBlockAck,
    CompressionBlockInbound,
    SessionCloseAck,
    SessionCloseInbound,
)
from .types import SessionBlockRecord


class SessionMemoryChannel:
    """Memory ↔ Speak 会话压缩双向边界。

    - 入站（Speak → Memory）：压缩块写入 SessionMemoryBuffer 临时社交图
    - 出站（Memory → Speak）：可选回调，通知块已缓冲 / 会话已整合

    压缩块仅作 Speak→Memory 临时社交锚（可选）；体验擢升走 Life ``ingest_compression_block`` → ``life.io.memory``。
    """

    def __init__(self, buffer: SessionMemoryBuffer | None = None) -> None:
        self._buffer = buffer
        self._on_buffered: Callable[[CompressionBlockAck], None] | None = None
        self._on_closed: Callable[[SessionCloseAck], None] | None = None

    @property
    def buffer(self) -> SessionMemoryBuffer | None:
        return self._buffer

    def bind_buffer(self, buffer: SessionMemoryBuffer) -> None:
        self._buffer = buffer

    def on_compression_buffered(
        self,
        handler: Callable[[CompressionBlockAck], None] | None,
    ) -> None:
        self._on_buffered = handler

    def on_session_closed(
        self,
        handler: Callable[[SessionCloseAck], None] | None,
    ) -> None:
        self._on_closed = handler

    def ingest_compression_block(self, request: CompressionBlockInbound) -> CompressionBlockAck:
        block = request.block
        sid = block.session_id.strip()
        if self._buffer is None:
            ack = CompressionBlockAck(session_id=sid, record=None)
            if self._on_buffered is not None:
                self._on_buffered(ack)
            return ack

        record = self._buffer.ingest_session_block(
            block,
            interactor_id=request.interactor_id,
        )
        ack = CompressionBlockAck(session_id=sid, record=record)
        if self._on_buffered is not None:
            self._on_buffered(ack)
        return ack

    def close_session(self, request: SessionCloseInbound) -> SessionCloseAck:
        sid = request.session_id.strip()
        if self._buffer is None:
            ack = SessionCloseAck(session_id=sid, interactor_id=request.interactor_id.strip())
            if self._on_closed is not None:
                self._on_closed(ack)
            return ack

        merged = self._buffer.close_dialogue_session(
            sid,
            interactor_id=request.interactor_id,
            final_unit=request.final_unit,
        )
        ack = SessionCloseAck(
            session_id=sid,
            interactor_id=request.interactor_id.strip(),
            merged_node_ids=[node.id for node in merged],
        )
        if self._on_closed is not None:
            self._on_closed(ack)
        return ack
