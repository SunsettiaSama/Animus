from __future__ import annotations

from collections.abc import Callable

from ..contracts import FilledSegment
from ..directors.reply.stream import StreamSink
from ..directors.reply.typewriter import ReplyStreamer


EmitFn = Callable[[str], None]
FloorHook = Callable[[], None]


class DeliveryExecutor:
    """
    非导演：正文推送交给 ReplyStreamer（吐字时序在 reply 侧）。
    吐字前后可挂 floor hook（typing ↔ awaiting_user）。
    """

    def __init__(
        self,
        *,
        emit: EmitFn | None = None,
        sleep: bool = True,
        quiet: bool = True,
        streamer: ReplyStreamer | None = None,
        on_typing_start: FloorHook | None = None,
        on_typing_end: FloorHook | None = None,
    ) -> None:
        del sleep  # 吐字节奏由 ReplyStreamer 负责，不再按段 sleep
        self._emit = emit or (lambda line: print(line, flush=True))
        self._quiet = quiet
        self.streamer = streamer
        self.on_typing_start = on_typing_start
        self.on_typing_end = on_typing_end

    def execute(
        self,
        segments: tuple[FilledSegment, ...],
        *,
        think: str = "",
        sink: StreamSink | None = None,
    ) -> str:
        if not segments:
            return ""

        if self.on_typing_start is not None:
            self.on_typing_start()

        if self.streamer is not None:
            answer = self.streamer.push(segments, think=think, sink=sink)
            if self.on_typing_end is not None:
                self.on_typing_end()
            return answer

        parts: list[str] = []
        for index, seg in enumerate(segments):
            if not self._quiet:
                self._emit(f"[speak:{index + 1}/{len(segments)}] {seg.text}")
            parts.append(seg.text)
        if segments and not self._quiet:
            last = segments[-1]
            self._emit(f"[finish] continuity={last.continuity}")
        if self.on_typing_end is not None:
            self.on_typing_end()
        return "\n".join(parts)
