from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .collect import collect_status_injected
from .request import ComposePrepareRequest
from .store import SpeakStatusStore, apply_presence_status_update

if TYPE_CHECKING:
    from agent.soul.speak.compose.runner import SpeakComposeRunner


class InboundComposeGateway:
    """Presence 入站 → ``SpeakStatusStore`` + 触发 compose 预组装（``SoulService.on_presence_status_update`` 接线）。"""

    def __init__(self, compose_runner: SpeakComposeRunner) -> None:
        self._runner = compose_runner
        self._store = SpeakStatusStore()
        self._schedule_prepare: Callable[[ComposePrepareRequest], None] | None = None

    @property
    def status_store(self) -> SpeakStatusStore:
        return self._store

    @property
    def compose_runner(self) -> SpeakComposeRunner:
        return self._runner

    def attach_scheduler(
        self,
        schedule_prepare: Callable[[ComposePrepareRequest], None],
    ) -> None:
        self._schedule_prepare = schedule_prepare

    def on_presence_status_update(self, snap) -> None:
        apply_presence_status_update(self._store, snap)
        session_id = getattr(snap, "session_id", "tao")
        self._runner.invalidate(session_id)
        self.request_prepare(ComposePrepareRequest(session_id=session_id))

    def request_prepare(self, request: ComposePrepareRequest) -> None:
        if self._schedule_prepare is not None:
            self._schedule_prepare(request)

    def reset_session(self, session_id: str) -> None:
        self._store.reset_session(session_id)
        self._runner.invalidate(session_id)

    def collect_status(
        self,
        presence_snap,
        *,
        dialogue_compressed: str = "",
        max_presence_chars: int = 600,
    ):
        return collect_status_injected(
            presence_snap=presence_snap,
            dialogue_compressed=dialogue_compressed,
            max_presence_chars=max_presence_chars,
            status_store=self._store,
        )
