"""life.story.outbox — 出站口实现 + beat 账本（ack 状态机）。

- ``StoryOutbox``：实现 ``LifeStoryOutboxPort``——beat 补全（幂等键、时间戳）、
  保鲜期检查、经总线投递；
- ``BeatLedger``：实现 ``BeatAckReceiver``——记录待回执 beat 的状态迁移；
  终态（performed/expired/declined）后触发 ``on_advance`` 钩子（landmark 推进 /
  chronicle 归档由 life 侧后续接入），非终态（silenced/suppressed）允许改期重投。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from agent.soul.storybus import (
    BeatAck,
    BeatAckStatus,
    BeatDraft,
    LifeStoryBeat,
    LifeStoryOutboxPort,
    StoryProgressSync,
)

logger = logging.getLogger(__name__)

# 状态机（协议 §7.3）：
#   pending --performed/expired/declined--> 终态
#   pending --silenced/suppressed--> held（可 redeliver 回 pending）
_TERMINAL = {BeatAckStatus.performed, BeatAckStatus.expired, BeatAckStatus.declined}
_HOLD = {BeatAckStatus.silenced, BeatAckStatus.suppressed}


class StoryOutbox:
    """life 侧出站口：draft → beat → 总线。"""

    def __init__(self, deliver: Callable[[LifeStoryBeat], bool]) -> None:
        self._deliver = deliver
        self._seen: set[str] = set()

    def build(self, draft: BeatDraft) -> LifeStoryBeat | None:
        """两相投递之构造相：补幂等键与时间戳，做去重/保鲜预检，不投递。"""
        beat = draft.with_beat_id(f"beat-{uuid.uuid4().hex[:16]}")
        if beat.beat_id in self._seen:
            return None
        if beat.is_expired():
            logger.debug("[story.outbox] beat expired before delivery: %s", beat.beat_id)
            return None
        return beat

    def deliver(self, beat: LifeStoryBeat) -> bool:
        """两相投递之投递相（调用方应先 build 并自行记账）。"""
        if beat.beat_id in self._seen or beat.is_expired():
            return False
        ok = bool(self._deliver(beat))
        if ok:
            self._seen.add(beat.beat_id)
        return ok

    def emit(self, draft: BeatDraft) -> LifeStoryBeat | None:
        beat = self.build(draft)
        if beat is None:
            return None
        return beat if self.deliver(beat) else None

    # ── LifeStoryOutboxPort ────────────────────────────────────────────────
    def deliver_beat(self, beat: LifeStoryBeat) -> bool:
        if beat.beat_id in self._seen or beat.is_expired():
            return False
        self._seen.add(beat.beat_id)
        return self._deliver(beat)

    def sync_progress(self, sync: StoryProgressSync) -> None:
        # 进度由总线直投（无 ack）；经构造注入的总线句柄在 wiring 中补挂
        raise NotImplementedError("经 wiring 装配的总线句柄使用 bus.sync_progress")


class BeatLedger:
    """beat 回执账本：状态机校验 + 终态推进钩子。"""

    def __init__(
        self,
        *,
        on_advance: Callable[[LifeStoryBeat, BeatAckStatus], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._beats: dict[str, LifeStoryBeat] = {}
        self._state: dict[str, str] = {}          # beat_id → pending|held|<终态>
        self._on_advance = on_advance
        self._clock = clock

    # ── 记录 ───────────────────────────────────────────────────────────────
    def record(self, beat: LifeStoryBeat) -> None:
        self._beats.setdefault(beat.beat_id, beat)
        self._state.setdefault(beat.beat_id, "pending")

    def state_of(self, beat_id: str) -> str:
        return self._state.get(beat_id, "")

    def beat(self, beat_id: str) -> LifeStoryBeat | None:
        return self._beats.get(beat_id)

    def pending(self) -> list[LifeStoryBeat]:
        return [b for bid, b in self._beats.items() if self._state.get(bid) == "pending"]

    def held(self) -> list[LifeStoryBeat]:
        """被抑制/沉默挂起的 beat（silenced|suppressed）——改期重投的候选。"""
        return [b for bid, b in self._beats.items() if self._state.get(bid) == "held"]

    def sweep_expired(self) -> list[LifeStoryBeat]:
        """保鲜期到点未终态的 beat（pending 与 held）标记 expired。"""
        expired: list[LifeStoryBeat] = []
        now = self._clock()
        for bid, beat in list(self._beats.items()):
            if self._state.get(bid) not in ("pending", "held"):
                continue
            if beat.is_expired(now=now):
                self._transition(bid, BeatAckStatus.expired)
                expired.append(beat)
        return expired

    # ── BeatAckReceiver ────────────────────────────────────────────────────
    def receive_ack(self, ack: BeatAck) -> None:
        try:
            status = BeatAckStatus(ack.status_value())
        except ValueError:
            logger.warning("[story.ledger] unknown ack status: %r", ack.status)
            return
        bid = ack.beat_id
        current = self._state.get(bid)
        if current is None:
            logger.debug("[story.ledger] ack for unknown beat: %s", bid)
            return
        if current in {s.value for s in _TERMINAL}:
            logger.debug("[story.ledger] ack on terminal beat ignored: %s %s", bid, current)
            return
        self._transition(bid, status)

    def _transition(self, beat_id: str, status: BeatAckStatus) -> None:
        if status in _TERMINAL:
            self._state[beat_id] = status.value
        elif status in _HOLD:
            self._state[beat_id] = "held"
        else:  # pragma: no cover - 状态枚举扩展时兜底
            return
        beat = self._beats.get(beat_id)
        if self._on_advance is not None and beat is not None:
            try:
                self._on_advance(beat, status)
            except Exception:  # noqa: BLE001 — 推进钩子失败不污染账本
                logger.exception("[story.ledger] on_advance failed for %s", beat_id)
