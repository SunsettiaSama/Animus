from __future__ import annotations

import threading
import time
from typing import Callable

from infra.base_service import BaseServiceManager

from .experience.builder import ExperienceBuilder
from .experience.unit import ExperienceActionKind, ExperienceUnit
from .journal.dice import DiceResult, roll_d100
from .journal.filler import LandmarkFiller, NullLandmarkFiller
from .journal.item import Landmark, LandmarkStatus
from .journal.journal import LifeJournal
from .journal.store import JournalStore

_WAKE_POLL_SEC = 0.5


class LifeService(BaseServiceManager):
    """Life 模块线程服务——将体验加工异步化，不阻塞 TaoLoop 主通路。

    架构
    ----
    - **即时层**（ExperienceBuilder）：原始输入 → ExperienceUnit → 热存储 + Chronicle
    - **手账层**（LifeJournal）：Agent 的地标时间轴与自述
    - **地标填充**（LandmarkFiller）：到点后调用 API 填充情节 → ExperienceUnit
    - **后台线程**：异步消费 ``enqueue_*`` 任务，心跳检查到期地标

    地标处理时机
    ------------
    1. 服务启动时：扫描并标记所有超时地标（overdue），立即入队处理
    2. 心跳 tick：检查所有 due 地标，入队处理
    3. 处理流程：LandmarkFiller.fill() → ExperienceBuilder.record_story_beat()
       → Landmark.mark_done() → JournalStore.save()
    """

    def __init__(
        self,
        builder: ExperienceBuilder,
        journal: LifeJournal,
        journal_store: JournalStore | None = None,
        filler: LandmarkFiller | None = None,
        tick_interval_sec: float = 60.0,
        profile_narrative: str = "",
        recent_memories: list[str] | None = None,
    ) -> None:
        self._builder = builder
        self._journal = journal
        self._journal_store = journal_store
        self._filler: LandmarkFiller = filler or NullLandmarkFiller()
        self._tick_interval = tick_interval_sec
        self._profile_narrative = profile_narrative
        self._recent_memories: list[str] = recent_memories or []
        self._tasks: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── BaseServiceManager ────────────────────────────────────────────────────

    def start(self, **kwargs) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._scan_and_enqueue_overdue()
        t = threading.Thread(target=self._run, name="life-service", daemon=True)
        t.start()
        self._thread = t

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def status(self) -> dict:
        state = "running" if (self._thread and self._thread.is_alive()) else "stopped"
        with self._lock:
            queued = len(self._tasks)
        due = len(self._journal.due_landmarks())
        return {
            "state":         state,
            "queued":        queued,
            "due_landmarks": due,
        }

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── 上下文更新（由 LifeManager 在有新数据时调用）─────────────────────────

    def update_context(
        self,
        profile_narrative: str = "",
        recent_memories: list[str] | None = None,
    ) -> None:
        """更新填充器使用的上下文（画像 + 记忆检索）。"""
        if profile_narrative:
            self._profile_narrative = profile_narrative
        if recent_memories is not None:
            self._recent_memories = recent_memories

    def set_filler(self, filler: LandmarkFiller) -> None:
        """热替换填充器实现（LLM 就绪后调用）。"""
        self._filler = filler

    # ── 非阻塞入队（TaoLoop 调用侧）────────────────────────────────────────

    def enqueue_user_turn(
        self,
        session_id: str,
        turn_index: int,
        user_text: str,
        agent_reply: str,
        salience: float = 0.3,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
    ) -> None:
        """非阻塞：将用户回合提交至后台线程。"""
        self._enqueue(lambda: self._builder.record_user_turn(
            session_id=session_id,
            turn_index=turn_index,
            user_text=user_text,
            agent_reply=agent_reply,
            salience=salience,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=activated_memory_ids,
        ))

    def enqueue_story_beat(
        self,
        narrative_hint: str,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        salience: float = 0.0,
        action_kind: ExperienceActionKind = ExperienceActionKind.reasoning,
    ) -> None:
        """非阻塞：将故事引擎产出提交至后台线程。"""
        self._enqueue(lambda: self._builder.record_story_beat(
            narrative_hint=narrative_hint,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            salience=salience,
            action_kind=action_kind,
        ))

    # ── 同步接口（心跳调用侧）────────────────────────────────────────────────

    def tick(self) -> list[ExperienceUnit]:
        """心跳驱动批处理（同步）：扫描热存储，擢升显著体验，清仓过期条目。"""
        return self._builder.tick()

    # ── 手账 ──────────────────────────────────────────────────────────────────

    @property
    def journal(self) -> LifeJournal:
        return self._journal

    @property
    def builder(self) -> ExperienceBuilder:
        return self._builder

    # ── 内部 ──────────────────────────────────────────────────────────────────

    def _enqueue(self, task: Callable[[], None]) -> None:
        with self._lock:
            self._tasks.append(task)
        self._wake.set()

    def _scan_and_enqueue_overdue(self) -> None:
        """启动时扫描超时地标，立即入队处理。"""
        overdue = self._journal.scan_overdue()
        for lm in overdue:
            self._enqueue_fill_landmark(lm)
        if overdue and self._journal_store is not None:
            self._journal_store.save(self._journal)

    def _enqueue_fill_landmark(self, landmark: Landmark) -> None:
        lm_id = landmark.id
        self._enqueue(lambda: self._fill_landmark(lm_id))

    def _fill_landmark(self, landmark_id: str) -> None:
        """填充一个地标：投骰 → 调用 Filler → 内化为 ExperienceUnit → Chronicle → 保存手账。"""
        lm = self._journal.get_landmark(landmark_id)
        if lm is None or lm.status == LandmarkStatus.done:
            return

        lm.mark_processing()

        dice = roll_d100()
        context_landmarks = self._journal.recent_done()
        narrative = self._filler.fill(
            landmark=lm,
            profile_narrative=self._profile_narrative,
            recent_memories=self._recent_memories,
            recent_landmarks=context_landmarks,
            dice=dice,
        )

        unit = self._builder.record_story_beat(
            narrative_hint=narrative,
            salience=0.6,
            action_kind=ExperienceActionKind.deciding,
        )
        lm.mark_done(
            narrative=narrative,
            experience_id=unit.id,
            dice_value=dice.value,
            dice_tendency=dice.tendency,
        )
        self._append_landmark_chronicle(lm, unit.id, dice)

        if self._journal_store is not None:
            self._journal_store.save(self._journal)

    def _append_landmark_chronicle(
        self,
        lm: Landmark,
        experience_id: str,
        dice: DiceResult | None = None,
    ) -> None:
        """地标完成后写入 Chronicle（landmark 类型），附带骰点倾向标注。"""
        chronicle_store = self._builder._chronicle_store
        if chronicle_store is None:
            return
        from .chronicle.entry import ChronicleEntry, ChronicleKind
        summary = lm.intention[:60]
        if dice is not None:
            summary = f"{summary}（d100={dice.value}，{dice.tendency}）"
        chronicle_store.append(ChronicleEntry(
            kind=ChronicleKind.landmark,
            summary=summary,
            salience=0.6,
            experience_id=experience_id,
        ))

    def _check_and_enqueue_due(self) -> None:
        """心跳时检查所有到期地标，入队处理。"""
        for lm in self._journal.due_landmarks():
            if lm.status == LandmarkStatus.overdue:
                lm.mark_overdue()
            self._enqueue_fill_landmark(lm)

    def _run(self) -> None:
        last_tick = time.monotonic()
        while not self._stop.is_set():
            remaining = self._tick_interval - (time.monotonic() - last_tick)
            self._wake.wait(timeout=max(min(remaining, _WAKE_POLL_SEC), 0.0))
            self._wake.clear()

            with self._lock:
                pending, self._tasks = self._tasks, []
            for task in pending:
                task()

            if time.monotonic() - last_tick >= self._tick_interval:
                self._builder.tick()
                self._check_and_enqueue_due()
                last_tick = time.monotonic()
