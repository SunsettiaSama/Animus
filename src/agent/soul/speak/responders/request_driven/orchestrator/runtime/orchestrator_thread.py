from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.soul.workers import DomainWorker
from infra.threading import ThreadLease, get_thread_registry

from .ingress import IngressEvent

if TYPE_CHECKING:
    from ...directors.coordinator import DirectorCoordinator
    from ..state import StateStore

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorThreadConfig:
    poll_check_ms: int = 200
    session_max_sec: float = 1800.0


class OrchestratorThread:
    """orchestrator 独立调度线程：事件队列、session 键控串行、生命周期。"""

    def __init__(
        self,
        *,
        state_store: StateStore,
        coordinator: DirectorCoordinator | None = None,
        on_delivery_ready: Callable[[str, str], None] | None = None,
        on_character_handoff: Callable[[str, dict[str, Any]], None] | None = None,
        config: OrchestratorThreadConfig | None = None,
    ) -> None:
        self._state_store = state_store
        self._coordinator = coordinator
        self._on_delivery_ready = on_delivery_ready
        self._on_character_handoff = on_character_handoff
        self._config = config or OrchestratorThreadConfig()
        self._worker = DomainWorker("speak-orchestrator-thread", owner="speak")
        self._session_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._poll_stop = threading.Event()
        self._poll_lease: ThreadLease | None = None
        self._active_sessions: set[str] = set()
        self._active_guard = threading.Lock()
        # activate 代数：reset 异步 close 不得踢掉已重连的新一代
        self._session_epochs: dict[str, int] = {}
        # 同一 session 至多一条 poll 在队列/执行中，避免 append+idle 双轨把 LLM 打爆
        self._poll_pending: set[str] = set()
        self._poll_pending_guard = threading.Lock()

    @property
    def state_store(self) -> StateStore:
        return self._state_store

    def bind_coordinator(self, coordinator: DirectorCoordinator) -> None:
        self._coordinator = coordinator

    def bind_delivery_ready(self, handler: Callable[[str, str], None] | None) -> None:
        self._on_delivery_ready = handler

    def bind_character_handoff(
        self,
        handler: Callable[[str, dict[str, Any]], None] | None,
    ) -> None:
        self._on_character_handoff = handler

    def start(self) -> None:
        self._worker.start()
        self._poll_stop.clear()
        if self._poll_lease is None or not self._poll_lease.is_alive():
            lease = get_thread_registry().request(
                "speak",
                "speak-orchestrator-poll",
                self._poll_loop,
                daemon=True,
                stop=self._poll_stop.set,
            )
            lease.start()
            self._poll_lease = lease

    def stop(self) -> None:
        self._poll_stop.set()
        self._worker.stop()
        if self._poll_lease is not None:
            self._poll_lease.stop(timeout=5.0)
            self._poll_lease = None

    def activate_session(self, session_id: str) -> int:
        """把会话纳入轮询扫描（进房/生命线打开时调用，不必等用户首条消息）。"""
        sid = session_id.strip()
        if not sid:
            return 0
        with self._active_guard:
            epoch = int(self._session_epochs.get(sid, 0)) + 1
            self._session_epochs[sid] = epoch
            self._active_sessions.add(sid)
        with self._poll_pending_guard:
            self._poll_pending.discard(sid)
        return epoch

    def deactivate_session(self, session_id: str, *, epoch: int | None = None) -> bool:
        """同步移出扫描。epoch 给定时仅当仍是该代才生效（防 reset 竞态）。"""
        sid = session_id.strip()
        if not sid:
            return False
        with self._active_guard:
            current = int(self._session_epochs.get(sid, 0))
            if epoch is not None and current != int(epoch):
                return False
            self._active_sessions.discard(sid)
        with self._poll_pending_guard:
            self._poll_pending.discard(sid)
        return True

    def session_epoch(self, session_id: str) -> int:
        sid = session_id.strip()
        with self._active_guard:
            return int(self._session_epochs.get(sid, 0))

    def notify_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> None:
        sid = session_id.strip()
        with self._active_guard:
            self._active_sessions.add(sid)
        text = user_text.strip()
        fast = IngressEvent(
            kind="user_input",
            session_id=sid,
            user_text=text,
            turn_index=turn_index,
            phase="fast",
        )
        self._enqueue_session(sid, lambda: self._handle_event(fast))

    def submit_user_input_sync(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
        timeout_sec: float = 8.0,
    ):
        """仅同步 fast 首响应帧；导演/编剧慢路径改由满 K 轮往来或 unit 门槛唤醒。"""
        sid = session_id.strip()
        with self._active_guard:
            self._active_sessions.add(sid)
        text = user_text.strip()
        fast = IngressEvent(
            kind="user_input",
            session_id=sid,
            user_text=text,
            turn_index=turn_index,
            phase="fast",
        )
        lock = self._session_lock(sid)

        def _run_fast():
            with lock:
                self._handle_event(fast)
            state = self._state_store.session(sid)
            return state.pending_delivery_plan or state.delivery_plan

        future = self._worker.submit(_run_fast)
        return future.result(timeout=timeout_sec)

    def notify_session_close(self, session_id: str) -> None:
        """关闭会话：同步 deactivate，异步清理；带 epoch 防止踢掉已重连会话。"""
        sid = session_id.strip()
        epoch = self.session_epoch(sid)
        self.deactivate_session(sid, epoch=epoch)

        def _run() -> None:
            # 仅清理仍停留在关闭代数的状态；若已 activate 新一代则跳过
            if self.session_epoch(sid) != epoch:
                return
            self._close_session(sid, epoch=epoch)

        self._enqueue_session(sid, _run)

    def notify_delivery_done(self, session_id: str) -> None:
        sid = session_id.strip()
        event = IngressEvent(kind="delivery_done", session_id=sid)
        self._enqueue_session(sid, lambda: self._handle_event(event))

    def status(self) -> dict[str, Any]:
        worker_status = self._worker.status()
        with self._active_guard:
            active = sorted(self._active_sessions)
        return {
            "worker": worker_status,
            "active_sessions": active,
        }

    def _enqueue_session(self, session_id: str, task: Callable[[], None]) -> None:
        lock = self._session_lock(session_id)

        def _run() -> None:
            with lock:
                task()

        self._worker.enqueue(_run)

    def _session_lock(self, session_id: str) -> threading.Lock:
        sid = session_id.strip()
        with self._locks_guard:
            if sid not in self._session_locks:
                self._session_locks[sid] = threading.Lock()
            return self._session_locks[sid]

    def _handle_event(self, event: IngressEvent) -> None:
        if event.kind == "session_close":
            # 正式关闭走 notify_session_close（带 epoch）；此处忽略裸事件
            return
        if self._coordinator is None:
            return
        if event.kind == "user_input":
            phase = str(getattr(event, "phase", "") or "").strip().lower()
            if phase not in ("fast", "slow"):
                raise ValueError(f"user_input phase must be fast|slow, got {phase!r}")
            self._coordinator.on_user_input(
                event.session_id,
                event.user_text,
                turn_index=event.turn_index,
                phase=phase,
            )
            # 用户入站不经导演催生角色；角色由 sync turn（origin=user）直回
            state = self._state_store.session(event.session_id)
            state.pending_character_handoff = None
            return
        if event.kind == "delivery_done":
            self._coordinator.on_delivery_done(event.session_id)
            # 出站结束后：若有导演主动 due handoff，再交角色
            self._maybe_notify_character_handoff(event.session_id)
            return
        if event.kind == "poll_tick":
            # 同一 poll 拍导演只向角色请求一次：
            # due 先快交；若已交过，poll_finish 不得再 notify 第二次。
            due_handoff = self._coordinator.dispatch_due_handoff(event.session_id)
            handed_off = False
            if due_handoff is not None:
                self._maybe_notify_character_handoff(event.session_id)
                handed_off = True
            self._coordinator.on_poll_tick(
                event.session_id,
                trigger=event.trigger,
            )
            if not handed_off:
                self._maybe_notify_character_handoff(event.session_id)
            elif self._coordinator.peek_character_handoff(event.session_id) is not None:
                # 本拍已请求过：清掉 poll 链误写的第二次 pending，防 delivery_done 再打
                state = self._state_store.session(event.session_id)
                state.pending_character_handoff = None
                state.notes.append(
                    "character_handoff: drop_duplicate_pending_after_due_notify"
                )

    def _maybe_notify_delivery(self, session_id: str, *, trigger: str) -> None:
        # 占位导演文案不再直接推前端；角色交接走 _maybe_notify_character_handoff
        del session_id, trigger

    def _maybe_notify_character_handoff(self, session_id: str) -> None:
        if self._on_character_handoff is None or self._coordinator is None:
            return
        # 先 take，避免并发双推；若仍在 pushing，handler 会交还
        handoff = self._coordinator.take_character_handoff(session_id)
        if handoff is None:
            return
        self._on_character_handoff(session_id, handoff)

    def _close_session(self, session_id: str, *, epoch: int | None = None) -> None:
        sid = session_id.strip()
        with self._active_guard:
            current = int(self._session_epochs.get(sid, 0))
            if epoch is not None and current != int(epoch):
                # 已有更新一代 activate，忽略过期 close
                return
            self._active_sessions.discard(sid)
        with self._poll_pending_guard:
            self._poll_pending.discard(sid)
        with self._active_guard:
            if epoch is not None and int(self._session_epochs.get(sid, 0)) != int(epoch):
                return
            if sid in self._active_sessions:
                return
        self._state_store.clear_session(sid)
        with self._locks_guard:
            self._session_locks.pop(sid, None)

    def _poll_loop(self) -> None:
        while not self._poll_stop.is_set():
            now = time.monotonic()
            with self._active_guard:
                sessions = list(self._active_sessions)
            for sid in sessions:
                with self._poll_pending_guard:
                    if sid in self._poll_pending:
                        continue
                due_trigger = ""
                # 仅帧数管理器阶梯可开拍；节奏表 due 不得绕过 5→15→30…
                for trigger in ("append", "idle"):
                    frame_mgr = self._state_store.poll_frame_manager(sid, trigger)
                    if frame_mgr.is_session_expired():
                        self.notify_session_close(sid)
                        due_trigger = ""
                        break
                    if not frame_mgr.armed:
                        continue
                    if frame_mgr.next_fire_at <= 0:
                        frame_mgr.schedule_next()
                        continue
                    if now >= frame_mgr.next_fire_at:
                        decision = frame_mgr.take_due_frame(now=now)
                        if decision.execute:
                            due_trigger = trigger
                            break
                        # 跳过帧：已在 take_due_frame 内预约下一 t，继续看其他 trigger
                        continue
                if not due_trigger:
                    continue
                # 到期执行帧：卸武装，消除双轨竞态；业务结束再 schedule_next
                for trigger in ("append", "idle"):
                    frame_mgr = self._state_store.poll_frame_manager(sid, trigger)
                    frame_mgr.armed = False
                    if trigger != due_trigger:
                        frame_mgr.next_fire_at = 0.0
                with self._poll_pending_guard:
                    if sid in self._poll_pending:
                        continue
                    self._poll_pending.add(sid)
                event = IngressEvent(
                    kind="poll_tick",
                    session_id=sid,
                    trigger=due_trigger,
                )

                def _run(e=event, session=sid) -> None:
                    try:
                        self._handle_event(e)
                    finally:
                        with self._poll_pending_guard:
                            self._poll_pending.discard(session)

                self._enqueue_session(sid, _run)
            time.sleep(self._config.poll_check_ms / 1000.0)
