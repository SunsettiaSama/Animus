from __future__ import annotations

from .channel import LifeMemoryChannel
from .deps import LifeIODeps
from .request import (
    DialogueCloseInbound,
    ExperienceIngestInbound,
    ExperienceRetractInbound,
)


class LifeMemoryIO:
    """Memory ↔ Life 顶层 I/O（Soul / Life 编排器经此交换数据）。"""

    def __init__(
        self,
        *,
        channel: LifeMemoryChannel,
        deps: LifeIODeps,
    ) -> None:
        self._channel = channel
        self._deps = deps
        self._port = None

    @property
    def deps(self) -> LifeIODeps:
        return self._deps

    @property
    def port(self):
        if self._port is None:
            from .adapter import LifeMemoryPortAdapter

            self._port = LifeMemoryPortAdapter(self)
        return self._port

    def submit_experience(self, inbound: ExperienceIngestInbound) -> None:
        self._deps.enqueue_write(
            lambda: self._channel.ingest_experience(inbound),
        )

    def submit_dialogue_close(self, inbound: DialogueCloseInbound) -> None:
        self._deps.enqueue_write(
            lambda: self._channel.close_dialogue_session(inbound),
        )

    def retract_experience(self, inbound: ExperienceRetractInbound) -> bool:
        return self._channel.retract_experience(inbound)
