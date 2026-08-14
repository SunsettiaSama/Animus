from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from ..contracts import TextGenerator
from ..directors.rhythm.on_scene import (
    compute_on_scene,
    on_scene_brief,
    should_refresh_on_scene,
)
from ..io.inbound import SpeakInbound
from ..stage import StageState
from ..stage.on_scene import OnSceneState


class OnSceneAsyncInjector:
    """
    临场异步泵：rhythm 判定到期后踢后台计算，完成经 inbound 注入。

    关键路径只 drain + kick，不 await LLM，避免拼装/回复卡顿。
    compose 永远读 stage 上「已注入的最新临场」。
    """

    def __init__(
        self,
        llm: TextGenerator,
        inbound: SpeakInbound,
        *,
        every_k: int = 3,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._llm = llm
        self._inbound = inbound
        self.every_k = max(1, int(every_k))
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="speak-on-scene",
        )
        self._future: Future[OnSceneState] | None = None
        self._lock = Lock()
        self._inbox: OnSceneState | None = None

    def _on_done(self, fut: Future[OnSceneState]) -> None:
        with self._lock:
            if self._future is fut:
                self._future = None
            self._inbound.stage.on_scene_pending = False
            self._inbox = fut.result()

    def _harvest_done_future(self) -> None:
        """主线程兜底：收回已完成 future（防 callback 未跑 / GIL 饿死）。"""
        with self._lock:
            fut = self._future
        if fut is None or not fut.done():
            return
        with self._lock:
            if self._future is fut:
                self._future = None
            if self._inbox is None:
                self._inbound.stage.on_scene_pending = False
                self._inbox = fut.result()

    def drain(self) -> OnSceneState | None:
        """收割已完成临场并注入 stage；未完成则 None（不阻塞等 LLM）。"""
        if self._inbound.stage.on_scene_pending or self._future is not None:
            time.sleep(0.001)
        self._harvest_done_future()
        with self._lock:
            state = self._inbox
            self._inbox = None
        if state is None:
            return None
        self._inbound.inject_on_scene(state)
        return state

    def kick_if_due(self, stage: StageState) -> bool:
        """到期则提交后台任务；已在途或未到期返回 False。"""
        self._harvest_done_future()
        with self._lock:
            busy = self._future is not None or self._inbox is not None
        if busy:
            return False
        if not should_refresh_on_scene(stage, every_k=self.every_k):
            return False
        brief = on_scene_brief(stage)
        beat_index = stage.poll_index
        stage.mark_on_scene_pending()
        fut = self._executor.submit(
            compute_on_scene,
            self._llm,
            brief,
            beat_index=beat_index,
        )
        with self._lock:
            self._future = fut
        fut.add_done_callback(self._on_done)
        return True

    def poll_and_kick(self, stage: StageState) -> OnSceneState | None:
        """每拍入口：先收割，再按需踢下一轮。"""
        drained = self.drain()
        self.kick_if_due(stage)
        return drained

    def shutdown(self, *, wait: bool = False) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=wait)
