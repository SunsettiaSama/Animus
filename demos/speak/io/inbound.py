from __future__ import annotations

from ..stage import StageState
from ..stage.models import ShareEvent
from ..stage.on_scene import OnSceneState


class SpeakInbound:
    """
    Speak 入站：外界状态注入的统一口。

    分享队列只在这里入队；临场异步结果也从这里注入。
    rhythm 读取/消费，compose 不维护队列、不轮询临场。
    """

    def __init__(self, stage: StageState) -> None:
        self._stage = stage

    @property
    def stage(self) -> StageState:
        return self._stage

    def inject_on_scene(self, state: OnSceneState) -> OnSceneState:
        """异步临场算完后注入；compose 下一拍拼装可读到。"""
        self._stage.set_on_scene(state)
        return state

    def inject_share(
        self,
        title: str,
        *,
        detail: str = "",
        urgency: float = 0.0,
        event_id: str = "",
    ) -> ShareEvent:
        if event_id.strip():
            event = ShareEvent(
                title=title.strip(),
                detail=detail.strip(),
                urgency=urgency,
                event_id=event_id.strip(),
            )
            self._stage.share_queue.append(event)
            return event
        return self._stage.enqueue_share(title, detail=detail, urgency=urgency)

    def inject_shares(self, events: list[ShareEvent] | tuple[ShareEvent, ...]) -> None:
        for event in events:
            self._stage.share_queue.append(event)

    def set_agent_status(self, status: str) -> None:
        self._stage.set_agent_status(status)

    def set_affect(
        self,
        *,
        intensity: float | None = None,
        label: str | None = None,
        valence: str | None = None,
    ) -> None:
        self._stage.set_affect(intensity=intensity, label=label, valence=valence)
