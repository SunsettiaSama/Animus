"""WorkerWorkService — confirm, run, monitor, and surface decline reasons."""
from __future__ import annotations

import threading
from typing import Any, Callable

from worker.work.adapter import WorkerAdapter, WorkerAdapterConfig
from worker.work.matcher import WorkIntentMatcher
from worker.work.types import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    WorkDecision,
    WorkEvent,
    WorkIntentSignal,
    WorkRecord,
    WorkStatus,
    utc_now_iso,
)

EventSink = Callable[[dict[str, Any]], None]


class WorkTransitionError(ValueError):
    pass


class WorkerWorkService:
    """Owns work registry, confirmation timeout, status transitions, and emits."""

    def __init__(
        self,
        *,
        llm_cfg_path: str,
        matcher: WorkIntentMatcher | None = None,
        confirmation_timeout_sec: float = 60.0,
        auto_decline_min_chars: int = 4,
        agent_state_service: Any = None,
        sandbox: Any = None,
        risk_gate: Any = None,
    ) -> None:
        self._matcher = matcher or WorkIntentMatcher()
        self._llm_cfg_path = llm_cfg_path
        self._confirmation_timeout_sec = confirmation_timeout_sec
        self._auto_decline_min_chars = auto_decline_min_chars
        self._agent_state_service = agent_state_service
        self._sandbox = sandbox
        self._risk_gate = risk_gate
        self._lock = threading.RLock()
        self._records: dict[str, WorkRecord] = {}
        self._adapters: dict[str, WorkerAdapter] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._sinks: dict[str, EventSink] = {}  # session_id → sink
        self._default_sink: EventSink | None = None

    def bind_agent_state_service(self, service: Any | None) -> None:
        self._agent_state_service = service

    def bind_runtime(
        self,
        *,
        sandbox: Any = None,
        risk_gate: Any = None,
    ) -> None:
        self._sandbox = sandbox
        self._risk_gate = risk_gate

    def run_lightweight_goal(
        self,
        goal: str,
        *,
        session_id: str = "",
        user_text: str = "",
        max_steps: int = 4,
        soul: Any = None,
    ) -> dict[str, Any]:
        """角色 io 分流用的轻量同步执行：自然语言目标 → 短跑 SubAgent，不含确认流。"""
        del user_text  # 保留签名供调用方；执行只看 goal
        text = str(goal or "").strip()
        if not text:
            return {"ok": False, "observation": "", "reason": "empty_goal"}
        adapter = WorkerAdapter(
            WorkerAdapterConfig(
                llm_cfg_path=self._llm_cfg_path,
                card_id="executor",
                max_steps=max(1, int(max_steps)),
            )
        )
        adapter.bind_runtime(sandbox=self._sandbox, risk_gate=self._risk_gate)
        result = adapter.run_single_task(
            text,
            soul=soul,
            agent_state_service=self._agent_state_service,
            sandbox=self._sandbox,
            risk_gate=self._risk_gate,
        )
        answer = str(result.get("answer") or "").strip()
        return {
            "ok": bool(answer),
            "observation": answer[:1200],
            "reason": "" if answer else "empty_answer",
            "session_id": session_id.strip(),
            "runner": "worker.lightweight",
        }

    # ── sink wiring ───────────────────────────────────────────────────────────

    def set_default_sink(self, sink: EventSink | None) -> None:
        self._default_sink = sink

    def bind_session_sink(self, session_id: str, sink: EventSink) -> None:
        with self._lock:
            self._sinks[session_id] = sink

    def unbind_session_sink(self, session_id: str) -> None:
        with self._lock:
            self._sinks.pop(session_id, None)

    def _emit(self, record: WorkRecord, event: WorkEvent) -> None:
        record.events.append(event)
        payload = event.to_ws_dict(
            gen_id=record.signal.gen_id,
            session_id=record.signal.session_id,
        )
        sink = self._sinks.get(record.signal.session_id) or self._default_sink
        if sink is not None:
            sink(payload)

    # ── transitions ───────────────────────────────────────────────────────────

    def _transition(self, record: WorkRecord, next_status: WorkStatus) -> None:
        allowed = ALLOWED_TRANSITIONS.get(record.status, frozenset())
        if next_status not in allowed:
            raise WorkTransitionError(
                f"invalid work transition {record.status.value} → {next_status.value}"
            )
        record.status = next_status

    # ── intent entry ──────────────────────────────────────────────────────────

    def maybe_signal(
        self,
        question: str,
        *,
        session_id: str,
        channel_id: str,
        gen_id: str,
    ) -> WorkIntentSignal | None:
        return self._matcher.build_signal(
            question,
            session_id=session_id,
            channel_id=channel_id,
            gen_id=gen_id,
        )

    def submit_intent(self, signal: WorkIntentSignal) -> WorkDecision:
        """Register intent, auto-decline or ask user for confirmation."""
        with self._lock:
            record = WorkRecord(signal=signal, status=WorkStatus.detected)
            self._records[signal.work_id] = record
            self._emit(
                record,
                WorkEvent(
                    type="work_intent_detected",
                    work_id=signal.work_id,
                    status=record.status.value,
                    message="检测到可能的任务意图",
                    payload={
                        "question": signal.question,
                        "matched_terms": list(signal.matched_terms),
                        "confidence": signal.confidence,
                        "reason": signal.reason,
                    },
                    seq=record.next_seq(),
                ),
            )
            decision = self._lightweight_decide(signal)
            record.decision = decision

            if decision.decision != "needs_work":
                self._transition(record, WorkStatus.declined)
                self._emit(
                    record,
                    WorkEvent(
                        type="work_declined",
                        work_id=signal.work_id,
                        status=record.status.value,
                        message=decision.reason,
                        reason=decision.reason,
                        reason_code=decision.reason_code,
                        payload={
                            "fallback_to_speak": decision.fallback_to_speak,
                            "surface_to_user": True,
                        },
                        seq=record.next_seq(),
                    ),
                )
                if decision.fallback_to_speak:
                    self._emit_fallback(record, decision.reason, decision.reason_code)
                return decision

            self._transition(record, WorkStatus.pending_confirmation)
            prompt = (
                f"看起来你想让我干活：「{signal.question}」。"
                "要交给 Worker 执行吗？"
            )
            self._emit(
                record,
                WorkEvent(
                    type="work_confirmation_required",
                    work_id=signal.work_id,
                    status=record.status.value,
                    message=prompt,
                    payload={
                        "prompt": prompt,
                        "suggested_action": decision.suggested_action or "run_single_task",
                        "question": signal.question,
                        "matched_terms": list(signal.matched_terms),
                        "timeout_sec": self._confirmation_timeout_sec,
                    },
                    seq=record.next_seq(),
                ),
            )
            self._arm_timeout(signal.work_id)
            return decision

    def _lightweight_decide(self, signal: WorkIntentSignal) -> WorkDecision:
        q = signal.question.strip()
        if len(q) < self._auto_decline_min_chars:
            return WorkDecision(
                work_id=signal.work_id,
                decision="insufficient",
                reason="任务描述过短，不足以判断要做什么",
                reason_code="insufficient_detail",
                fallback_to_speak=True,
                requires_user_confirmation=False,
            )
        soft_refuse = {"你帮我吗", "你行吗", "你在吗", "你好", "你帮帮"}
        if q in soft_refuse:
            return WorkDecision(
                work_id=signal.work_id,
                decision="declined",
                reason="更像闲聊确认，不像具体任务",
                reason_code="chat_like",
                fallback_to_speak=True,
                requires_user_confirmation=False,
            )
        return WorkDecision(
            work_id=signal.work_id,
            decision="needs_work",
            reason="命中你+任务动词，需确认是否执行",
            reason_code="maybe_work",
            fallback_to_speak=True,
            suggested_action="run_single_task",
            requires_user_confirmation=True,
        )

    def _emit_fallback(self, record: WorkRecord, reason: str, reason_code: str) -> None:
        # Status stays declined/pending path; event tells Speak router to continue.
        self._emit(
            record,
            WorkEvent(
                type="work_fallback_to_speak",
                work_id=record.signal.work_id,
                status=record.status.value,
                message=reason or "回落到普通对话",
                reason=reason,
                reason_code=reason_code or "fallback",
                payload={
                    "question": record.signal.question,
                    "fallback_to_speak": True,
                },
                seq=record.next_seq(),
            ),
        )

    # ── confirmation / abort / monitor ────────────────────────────────────────

    def _arm_timeout(self, work_id: str) -> None:
        self._cancel_timeout(work_id)

        def _on_timeout() -> None:
            self.handle_confirmation(
                work_id,
                approved=False,
                reason="确认超时，未开始执行",
                reason_code="confirmation_timeout",
                from_timeout=True,
            )

        timer = threading.Timer(self._confirmation_timeout_sec, _on_timeout)
        timer.daemon = True
        with self._lock:
            self._timers[work_id] = timer
        timer.start()

    def _cancel_timeout(self, work_id: str) -> None:
        with self._lock:
            timer = self._timers.pop(work_id, None)
        if timer is not None:
            timer.cancel()

    def handle_confirmation(
        self,
        work_id: str,
        *,
        approved: bool,
        reason: str = "",
        reason_code: str = "",
        from_timeout: bool = False,
        soul: Any = None,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._records.get(work_id)
            if record is None:
                raise KeyError(f"unknown work_id: {work_id}")
            if record.status != WorkStatus.pending_confirmation:
                return {
                    "ok": False,
                    "work_id": work_id,
                    "status": record.status.value,
                    "reason": "not_pending_confirmation",
                }
            self._cancel_timeout(work_id)

            if not approved:
                self._transition(record, WorkStatus.declined)
                decline_reason = reason or (
                    "确认超时，未开始执行" if from_timeout else "用户拒绝执行"
                )
                code = reason_code or (
                    "confirmation_timeout" if from_timeout else "user_declined"
                )
                record.decision = WorkDecision(
                    work_id=work_id,
                    decision="declined",
                    reason=decline_reason,
                    reason_code=code,
                    fallback_to_speak=True,
                    requires_user_confirmation=False,
                )
                self._emit(
                    record,
                    WorkEvent(
                        type="work_declined",
                        work_id=work_id,
                        status=record.status.value,
                        message=decline_reason,
                        reason=decline_reason,
                        reason_code=code,
                        payload={"fallback_to_speak": True, "surface_to_user": True},
                        seq=record.next_seq(),
                    ),
                )
                self._emit_fallback(record, decline_reason, code)
                return {
                    "ok": True,
                    "work_id": work_id,
                    "status": record.status.value,
                    "fallback_to_speak": True,
                    "question": record.signal.question,
                    "reason": decline_reason,
                    "reason_code": code,
                }

            self._transition(record, WorkStatus.starting)
            record.started_at = utc_now_iso()
            self._emit(
                record,
                WorkEvent(
                    type="work_started",
                    work_id=work_id,
                    status=record.status.value,
                    message="Worker 开始准备任务",
                    payload={
                        "runner": "sub_agent",
                        "question": record.signal.question,
                    },
                    seq=record.next_seq(),
                ),
            )
            thread = threading.Thread(
                target=self._run_work,
                args=(work_id, soul),
                name=f"worker-work-{work_id[:8]}",
                daemon=True,
            )
            self._threads[work_id] = thread
            thread.start()
            return {
                "ok": True,
                "work_id": work_id,
                "status": WorkStatus.starting.value,
                "fallback_to_speak": False,
                "question": record.signal.question,
            }

    def inject_user_text(
        self,
        work_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("inject_user_text requires non-empty text")
        with self._lock:
            record = self._records.get(work_id)
            if record is None:
                raise KeyError(f"unknown work_id: {work_id}")
            if record.status != WorkStatus.running:
                raise WorkTransitionError(
                    f"inject_user_text only allowed while running, got {record.status.value}"
                )
            adapter = self._adapters.get(work_id)
        if adapter is None:
            raise RuntimeError(f"no active adapter for work_id={work_id}")
        ok = adapter.inject_user_text(clean, metadata=metadata)
        if not ok:
            raise RuntimeError(f"TaoLoop not ready for inject on work_id={work_id}")
        with self._lock:
            self._emit(
                record,
                WorkEvent(
                    type="work_progress",
                    work_id=work_id,
                    status=WorkStatus.running.value,
                    message="用户插话已置顶注入上下文",
                    payload={"phase": "user_inject", "text": clean[:240]},
                    seq=record.next_seq(),
                ),
            )
        return {"ok": True, "work_id": work_id, "status": WorkStatus.running.value}

    def running_work_for_session(self, session_id: str) -> str | None:
        with self._lock:
            for work_id, record in self._records.items():
                if (
                    record.signal.session_id == session_id
                    and record.status == WorkStatus.running
                ):
                    return work_id
        return None

    def abort(self, work_id: str, *, reason: str = "用户中止") -> dict[str, Any]:
        with self._lock:
            record = self._records.get(work_id)
            if record is None:
                raise KeyError(f"unknown work_id: {work_id}")
            if record.status in TERMINAL_STATUSES:
                return {"ok": True, "work_id": work_id, "status": record.status.value}
            record.abort_requested = True
            adapter = self._adapters.get(work_id)
            self._cancel_timeout(work_id)

            if record.status == WorkStatus.pending_confirmation:
                self._transition(record, WorkStatus.aborted)
                record.finished_at = utc_now_iso()
                self._emit(
                    record,
                    WorkEvent(
                        type="work_aborted",
                        work_id=work_id,
                        status=record.status.value,
                        message=reason,
                        reason=reason,
                        reason_code="user_abort",
                        payload={},
                        seq=record.next_seq(),
                    ),
                )
                return {"ok": True, "work_id": work_id, "status": record.status.value}

        if adapter is not None:
            adapter.request_abort()
        return {"ok": True, "work_id": work_id, "status": "abort_requested"}

    def monitor_snapshot(self, work_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._records.get(work_id)
            if record is None:
                raise KeyError(f"unknown work_id: {work_id}")
            snap = {
                "work_id": work_id,
                "status": record.status.value,
                "monitor": dict(record.monitor),
                "question": record.signal.question,
                "answer": record.answer,
                "error": record.error,
                "started_at": record.started_at,
                "finished_at": record.finished_at,
            }
            self._emit(
                record,
                WorkEvent(
                    type="work_monitor",
                    work_id=work_id,
                    status=record.status.value,
                    message="监控快照",
                    payload=snap,
                    seq=record.next_seq(),
                ),
            )
            return snap

    def get_record(self, work_id: str) -> WorkRecord | None:
        with self._lock:
            return self._records.get(work_id)

    def summary_for_history(self, work_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(work_id)
            if record is None:
                return None
            return record.summary_dict()

    # ── execution ─────────────────────────────────────────────────────────────

    def _run_work(self, work_id: str, soul: Any) -> None:
        with self._lock:
            record = self._records[work_id]
            adapter = WorkerAdapter(
                WorkerAdapterConfig(llm_cfg_path=self._llm_cfg_path, card_id="executor")
            )
            if self._sandbox is None or self._risk_gate is None:
                raise RuntimeError(
                    "WorkerWorkService 缺少 sandbox/risk_gate；"
                    "请在 AppState 启动时调用 bind_runtime()"
                )
            adapter.bind_runtime(sandbox=self._sandbox, risk_gate=self._risk_gate)
            self._adapters[work_id] = adapter
            self._transition(record, WorkStatus.running)
            self._emit(
                record,
                WorkEvent(
                    type="work_progress",
                    work_id=work_id,
                    status=record.status.value,
                    message="Worker 执行中",
                    payload={
                        "phase": "running",
                        "progress": 0.0,
                        "has_agent_state": self._agent_state_service is not None,
                    },
                    seq=record.next_seq(),
                ),
            )

        step_count = 0

        def _on_event(event: Any) -> None:
            nonlocal step_count
            if record.abort_requested:
                raise RuntimeError("work aborted")
            name = type(event).__name__
            if name == "StepEvent":
                step_count += 1
                step_payload = {
                    "phase": "step",
                    "step_index": getattr(event, "index", step_count),
                    "action": getattr(event, "action", ""),
                    "thought": (getattr(event, "thought", "") or "")[:240],
                    "progress": min(0.1 * step_count, 0.9),
                }
                with self._lock:
                    record.monitor = {
                        "step_count": step_count,
                        "last_action": step_payload.get("action", ""),
                        "updated_at": utc_now_iso(),
                    }
                    self._emit(
                        record,
                        WorkEvent(
                            type="work_progress",
                            work_id=work_id,
                            status=WorkStatus.running.value,
                            message=f"步骤 {step_payload['step_index']}",
                            payload=step_payload,
                            seq=record.next_seq(),
                        ),
                    )

        result: dict[str, Any] | None = None
        error: str | None = None
        try:
            result = adapter.run_single_task(
                record.signal.question,
                event_callback=_on_event,
                soul=soul,
                agent_state_service=self._agent_state_service,
                sandbox=self._sandbox,
                risk_gate=self._risk_gate,
            )
        except Exception as exc:
            error = str(exc)

        with self._lock:
            record = self._records[work_id]
            record.finished_at = utc_now_iso()
            if record.abort_requested or (error and "aborted" in error.lower()):
                if record.status not in TERMINAL_STATUSES:
                    self._transition(record, WorkStatus.aborted)
                record.error = error or "aborted"
                self._emit(
                    record,
                    WorkEvent(
                        type="work_aborted",
                        work_id=work_id,
                        status=WorkStatus.aborted.value,
                        message=record.error,
                        reason=record.error,
                        reason_code="aborted",
                        payload={},
                        seq=record.next_seq(),
                    ),
                )
                return
            if error is not None:
                self._transition(record, WorkStatus.failed)
                record.error = error
                self._emit(
                    record,
                    WorkEvent(
                        type="work_failed",
                        work_id=work_id,
                        status=WorkStatus.failed.value,
                        message=error,
                        reason=error,
                        reason_code="worker_error",
                        payload={"error": error},
                        seq=record.next_seq(),
                    ),
                )
                return

            assert result is not None
            record.answer = str(result.get("answer") or "")
            record.monitor = {
                "step_count": result.get("step_count", step_count),
                "runner": result.get("runner", "sub_agent"),
                "profile": result.get("profile", "executor"),
                "updated_at": utc_now_iso(),
            }
            self._transition(record, WorkStatus.finished)
            self._emit(
                record,
                WorkEvent(
                    type="work_finished",
                    work_id=work_id,
                    status=WorkStatus.finished.value,
                    message=record.answer or "任务完成",
                    payload={
                        "answer": record.answer,
                        "step_count": record.monitor.get("step_count", 0),
                        "steps_log": result.get("steps_log", []),
                    },
                    seq=record.next_seq(),
                ),
            )

        if self._agent_state_service is not None:
            self._agent_state_service.submit_refresh_fallback(force=False)
