"""输出忠实性审查官：对照上下文判断模型产出是否包含上下文未提及的主张。

定位：昂贵（额外一次 LLM 调用）、默认关闭（enabled=False）、异步（常驻工作
线程 FIFO，入队即返回）、静默（裁决只进日志与 obs 事件，不阻塞、不改写
answer、不触发重试）。判定失败一律降级为"不确定"，本模块永不 raise。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from infra.llm.llm import BaseLLM
from infra.threading import ThreadLease, get_thread_registry

logger = logging.getLogger(__name__)

_WAKE_POLL_SEC = 0.5
_MAX_UNSUPPORTED_ITEMS = 10
_MAX_ITEM_CHARS = 120

_AUDIT_PROMPT = """你是输出忠实性审查官。下面给出一轮对话的上下文（输入）与模型本次的产出（输出）。请判断：产出中是否包含上下文完全没有提及的事实性主张（编造的人物、事件、时间、数字、记忆等）。

判断规则：
- 只把"事实性主张"算作嫌疑；寒暄、推理过程、一般性常识、对上下文内容的复述或改写不算。
- 上下文没有提及、且无法从上下文直接推出的事实性主张，逐条列入 unsupported。
- 无法判断、或产出中没有事实性主张时，faithful 置为 true 并在 reason 说明。

上下文（输入）：
<<<CONTEXT
{context}
CONTEXT>>>

模型产出（输出）：
<<<OUTPUT
{output}
OUTPUT>>>

只输出一个 JSON 对象，不要输出其它内容：
{{"faithful": true, "unsupported": ["每条无依据的主张，简短"], "reason": "一句话理由"}}"""


@dataclass
class AuditorConfig:
    enabled: bool = False
    owner: str = "agent.auditor"
    name: str = ""
    # "finish" 只审 finish 步产出；"every_step" 审每次解析成功的产出。
    scope: str = "finish"
    max_context_chars: int = 6000
    max_output_chars: int = 2000


@dataclass
class AuditVerdict:
    faithful: bool | None = None  # None = 不确定（解析失败/LLM 异常）
    unsupported: list[str] = field(default_factory=list)
    reason: str = ""
    latency_ms: float = 0.0
    model: str = ""


@dataclass(frozen=True)
class _AuditTask:
    context: str
    output: str
    step_index: int
    scope: str


class OutputAuditor:
    """常驻单线程审查官：submit() 入队即返回，worker 逐条判定并静默记录。"""

    def __init__(self, llm: BaseLLM, cfg: AuditorConfig | None = None) -> None:
        self._llm = llm
        self._cfg = cfg or AuditorConfig()
        self._tasks: list[_AuditTask] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lease: ThreadLease | None = None
        self.verdicts: deque[tuple[_AuditTask, AuditVerdict]] = deque(maxlen=64)

    @property
    def cfg(self) -> AuditorConfig:
        return self._cfg

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    def submit(self, *, context: str, output: str, step_index: int = -1, scope: str = "finish") -> None:
        """异步提交一次审查；未启用时直接忽略。"""
        if not self._cfg.enabled:
            return
        task = _AuditTask(
            context=str(context or "")[-self._cfg.max_context_chars:],
            output=str(output or "")[-self._cfg.max_output_chars:],
            step_index=step_index,
            scope=str(scope or "finish"),
        )
        with self._lock:
            self._tasks.append(task)
        self._ensure_worker()
        self._wake.set()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._lease is not None:
            self._lease.stop(timeout=timeout)
            self._lease = None

    def status(self) -> dict[str, Any]:
        alive = self._lease is not None and self._lease.is_alive()
        with self._lock:
            queued = len(self._tasks)
        return {
            "enabled": self._cfg.enabled,
            "state": "running" if alive else "stopped",
            "queued": queued,
            "audited": len(self.verdicts),
        }

    # ── Worker（照 AgentService 的 FIFO + wake 模式） ────────────────────────

    def _ensure_worker(self) -> None:
        if self._lease is not None and self._lease.is_alive():
            return
        self._stop.clear()
        name = self._cfg.name.strip() or f"output-auditor-{id(self):x}"
        lease = get_thread_registry().request(
            self._cfg.owner,
            name,
            self._run,
            daemon=True,
            stop=self._signal_stop,
        )
        lease.start()
        self._lease = lease

    def _signal_stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=_WAKE_POLL_SEC)
            self._wake.clear()
            with self._lock:
                pending, self._tasks = self._tasks, []
            for task in pending:
                if self._stop.is_set():
                    break
                verdict = self._audit_one(task)
                self.verdicts.append((task, verdict))
                self._record(task, verdict)

    # ── 判定 ─────────────────────────────────────────────────────────────────

    def _audit_one(self, task: _AuditTask) -> AuditVerdict:
        prompt = _AUDIT_PROMPT.format(context=task.context, output=task.output)
        t0 = time.perf_counter()
        try:
            raw = self._llm.generate(prompt)
        except Exception as exc:
            return AuditVerdict(
                faithful=None,
                reason=f"llm_error:{type(exc).__name__}",
                latency_ms=(time.perf_counter() - t0) * 1000,
                model=self._model_name(),
            )
        latency_ms = (time.perf_counter() - t0) * 1000
        return self._parse_verdict(raw, latency_ms=latency_ms, model=self._model_name())

    def _parse_verdict(self, raw: str, *, latency_ms: float, model: str) -> AuditVerdict:
        text = str(raw or "").strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return AuditVerdict(
                faithful=None, reason="no_json_in_verdict", latency_ms=latency_ms, model=model
            )
        try:
            payload = json.loads(text[start:end])
        except json.JSONDecodeError:
            return AuditVerdict(
                faithful=None, reason="invalid_verdict_json", latency_ms=latency_ms, model=model
            )
        faithful = payload.get("faithful")
        if not isinstance(faithful, bool):
            faithful = None
        unsupported_raw = payload.get("unsupported")
        unsupported: list[str] = []
        if isinstance(unsupported_raw, list):
            for item in unsupported_raw[:_MAX_UNSUPPORTED_ITEMS]:
                line = str(item).strip()[:_MAX_ITEM_CHARS]
                if line:
                    unsupported.append(line)
        reason = str(payload.get("reason", "")).strip()[:200]
        return AuditVerdict(
            faithful=faithful,
            unsupported=unsupported,
            reason=reason,
            latency_ms=latency_ms,
            model=model,
        )

    def _model_name(self) -> str:
        inner = getattr(self._llm, "_llm", None)
        return str(
            getattr(self._llm, "_model_name", "")
            or getattr(inner, "_model_name", "")
            or ""
        )

    def _record(self, task: _AuditTask, verdict: AuditVerdict) -> None:
        level = logging.INFO if verdict.faithful is not False else logging.WARNING
        logger.log(
            level,
            "[Audit] scope=%s step=%s faithful=%s unsupported=%s reason=%r latency_ms=%.0f model=%r",
            task.scope,
            task.step_index,
            verdict.faithful,
            verdict.unsupported,
            verdict.reason,
            verdict.latency_ms,
            verdict.model,
        )
        try:
            from test.obs.collector import get_collector
            from test.obs.events import AuditEvent

            get_collector().emit(AuditEvent(
                session_id=get_collector().current_session(),
                ts=time.time(),
                model=verdict.model,
                scope=task.scope,
                step_index=task.step_index,
                faithful=verdict.faithful,
                unsupported=list(verdict.unsupported),
                reason=verdict.reason,
                latency_ms=verdict.latency_ms,
            ))
        except Exception:
            logger.debug("[Audit] obs emit failed", exc_info=True)
