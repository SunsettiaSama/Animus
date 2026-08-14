from __future__ import annotations

from typing import Any


class SpeakOutbound:
    """
    Speak 出站：流式 sink / delivery 对外挂接。

    正文推送仍走 ReplyStreamer；此处只做边界收拢。
    不 import runtime/directors，保持 io 分层。
    """

    def __init__(
        self,
        *,
        streamer: Any = None,
        delivery: Any = None,
    ) -> None:
        self.streamer = streamer
        self.delivery = delivery

    def bind_sink(self, sink: Any) -> None:
        if self.streamer is not None:
            self.streamer.bind_sink(sink)
        if self.delivery is not None and self.delivery.streamer is None:
            self.delivery.streamer = self.streamer

    def bind_streamer(self, streamer: Any) -> None:
        self.streamer = streamer
        if self.delivery is not None:
            self.delivery.streamer = streamer
