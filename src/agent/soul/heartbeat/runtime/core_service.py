from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.heartbeat.console_log import hb_debug, hb_info, hb_warning
from agent.soul.heartbeat.window import within_window
from agent.soul.heartbeat.policy import should_offer_inject
from agent.soul.heartbeat.inject_mailbox import (
    HeartbeatInjectMailbox,
    get_heartbeat_mailbox,
    set_global_mailbox,
)
from agent.soul.heartbeat.config import SoulHeartbeatConfig
from agent.soul.heartbeat.tick_log import HeartbeatTickResult

if TYPE_CHECKING:
    from agent.soul.heartbeat.runtime.module import HeartbeatModule

logger = logging.getLogger(__name__)

_AGENT_INJECT_SYSTEM = (
    "你是一个调度提示助手。根据下面的「心跳待注入摘要」，判断此时是否适合把该摘要并入用户下一轮对话的系统层附注。\n"
    "仅回复一行，且只能是 INJECT 或 DEFER 之一，不要其它文字。\n"
    "若当前适合注入（例如有待办需要用户感知），回复 INJECT；若应等待更适合的时机，回复 DEFER。"
)


def _effective_inject_window(cfg: SoulHeartbeatConfig) -> tuple[str, str, str]:
    start = cfg.inject_window_start or cfg.active_hours_start
    end = cfg.inject_window_end or cfg.active_hours_end
    tz = cfg.inject_timezone or cfg.active_timezone
    return start, end, tz


class HeartbeatCoreService:
    """Dedicated daemon thread: periodic heartbeat check + inject-window gating for ConvLoop."""

    def __init__(
        self,
        heartbeat: "HeartbeatModule",
        llm_service=None,
        llm_cfg_path: str = "config/llm_core/config.yaml",
        mailbox: HeartbeatInjectMailbox | None = None,
        register_global_mailbox: bool = True,
    ) -> None:
        self._heartbeat = heartbeat
        self._cfg: SoulHeartbeatConfig = heartbeat._cfg
        self._llm_service = llm_service
        self._llm_cfg_path = llm_cfg_path
        self._mailbox = mailbox or HeartbeatInjectMailbox()
        self._register_global = register_global_mailbox
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._deferred: str | None = None
        self._deferred_lock = threading.Lock()
        self._consecutive_failures = 0

    @property
    def mailbox(self) -> HeartbeatInjectMailbox:
        return self._mailbox

    @property
    def consecutive_failures(self) -> int:
        """连续迭代失败次数（健康观测口；成功一次即清零）。"""
        return self._consecutive_failures

    @property
    def is_running(self) -> bool:
        """主循环线程是否存活（vitals 探针读口）。"""
        return self._thread is not None and self._thread.is_alive()

    @property
    def deferred_pending(self) -> bool:
        """是否有窗口外/避让暂存的待注入文本（非破坏读）。"""
        with self._deferred_lock:
            return self._deferred is not None

    def start(self) -> None:
        if self._thread is not None:
            return
        if self._register_global:
            set_global_mailbox(self._mailbox)
        self._thread = threading.Thread(
            target=self._run,
            name="heartbeat-core",
            daemon=True,
        )
        self._thread.start()
        hb_info(
            logger,
            "[HeartbeatCore] started - poll=%ds mode=%s",
            self._cfg.poll_interval_sec,
            self._cfg.inject_window_mode,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30.0)
            if self._thread.is_alive():
                logger.warning(
                    "[HeartbeatCore] 线程未在 30s 内退出（可能被长调用阻塞），"
                    "将以 daemon 线程随进程退出",
                )
            self._thread = None
        if self._register_global and get_heartbeat_mailbox() is self._mailbox:
            set_global_mailbox(None)
        hb_info(logger, "[HeartbeatCore] stopped")

    def _run(self) -> None:
        interval = max(5, int(self._cfg.poll_interval_sec))
        while not self._stop.is_set():
            if self._stop.wait(timeout=interval):
                break
            self._safe_iteration()

    def _safe_iteration(self) -> bool:
        """单次迭代 + 兜异常：心跳是唤起线，任何故障不允许线程死亡。

        故障日志直写 logger.exception，不受 console_log_enabled 门控
        （该开关只管心跳常规日志）。返回本轮是否成功。
        """
        try:
            self._iteration()
        except Exception:  # noqa: BLE001
            self._consecutive_failures += 1
            logger.exception(
                "[HeartbeatCore] iteration 失败（连续第 %d 次，线程继续运行）",
                self._consecutive_failures,
            )
            return False
        self._consecutive_failures = 0
        return True

    def _iteration(self) -> None:
        self._flush_deferred_if_due()
        self._maybe_preflight()
        result = self._heartbeat.tick()
        text = self._payload_from_result(result)
        if not text:
            return
        allow, reason = should_offer_inject(self._vitals())
        if not allow:
            with self._deferred_lock:
                self._deferred = text
            hb_debug(logger, "[HeartbeatCore] inject deferred - %s", reason)
            return
        window_ok = self._within_inject_window()
        if not window_ok:
            with self._deferred_lock:
                self._deferred = text
            hb_debug(logger, "[HeartbeatCore] inject deferred - outside user inject window")
            return
        mode = (self._cfg.inject_window_mode or "user").strip().lower()
        if mode == "agent":
            if self._agent_accepts_inject(text):
                self._mailbox.offer(text)
                with self._deferred_lock:
                    self._deferred = None
            else:
                with self._deferred_lock:
                    self._deferred = text
                hb_debug(logger, "[HeartbeatCore] inject deferred - agent chose DEFER")
            return
        self._mailbox.offer(text)
        with self._deferred_lock:
            self._deferred = None

    def _flush_deferred_if_due(self) -> None:
        with self._deferred_lock:
            pending = self._deferred
        if not pending:
            return
        if not self._within_inject_window():
            return
        mode = (self._cfg.inject_window_mode or "user").strip().lower()
        if mode == "agent":
            if not self._agent_accepts_inject(pending):
                return
        self._mailbox.offer(pending)
        with self._deferred_lock:
            self._deferred = None
        hb_debug(logger, "[HeartbeatCore] flushed deferred inject")

    def _within_inject_window(self) -> bool:
        start, end, tz = _effective_inject_window(self._cfg)
        return within_window(start, end, tz)

    def _vitals(self):
        """读 module 的生命体征；module 未提供（未接线/假件）时返回 None。"""
        get_vitals = getattr(self._heartbeat, "vitals", None)
        if not callable(get_vitals):
            return None
        try:
            return get_vitals()
        except Exception:  # noqa: BLE001 — 体征读失败不阻断注入主路径
            logger.warning("[HeartbeatCore] vitals 读取失败，本轮按无体征处理", exc_info=True)
            return None

    def _payload_from_result(self, result: HeartbeatTickResult) -> str:
        if result.outcome == "skip":
            return ""
        return (result.detail_for_inject or "").strip()

    def _maybe_preflight(self) -> None:
        raw = (self._cfg.preflight_instruction or "").strip()
        if not raw:
            return
        soul = self._heartbeat._soul
        if soul is None:
            hb_warning(logger, "[HeartbeatCore] preflight skipped - soul not wired")
            return
        engine = soul.scheduler_engine
        if engine is None:
            hb_warning(logger, "[HeartbeatCore] preflight skipped - scheduler_engine not wired")
            return
        from agent.profile import SubAgentProfile
        from agent.runner import SubAgentRunner
        from agent.soul.heartbeat.schedule.profiles import make_default_scheduler_config

        scheduler_cfg = make_default_scheduler_config(llm_cfg_path=self._llm_cfg_path)
        base = scheduler_cfg.profiles.get("minimal") or SubAgentProfile()
        runner = SubAgentRunner()
        runner.run_sync(
            instruction=raw,
            profile=base,
            llm_cfg_path=self._llm_cfg_path,
            scheduler_engine=engine,
            notify_fn=None,
        )

    def _resolve_aux_llm(self):
        if self._llm_service is not None:
            llm = self._llm_service.get_aux_llm(self._cfg.llm_aux_name)
            if llm is not None:
                return llm
        from config.llm_core.config import LLMConfig
        from infra.llm.llm import LLM

        return LLM(LLMConfig.from_yaml(self._llm_cfg_path))

    def _agent_accepts_inject(self, text: str) -> bool:
        snippet = text[:1500]
        llm = self._resolve_aux_llm()
        if llm is None:
            return True
        messages = [
            SystemMessage(content=_AGENT_INJECT_SYSTEM),
            HumanMessage(content=f"[待判定摘要]\n{snippet}"),
        ]
        raw = self._call_judge_llm(llm, messages)
        if raw is None:
            return False  # 判定失败按 DEFER：pending 保留在 _deferred，下轮重试
        raw = raw.strip().upper()
        toks = raw.split()
        head = toks[0] if toks else ""
        if head == "DEFER" or raw.startswith("DEFER"):
            return False
        return head == "INJECT" or raw.startswith("INJECT")

    def _call_judge_llm(self, llm, messages) -> str | None:
        """一次性 daemon 线程 + 超时等待执行判定调用。

        LLM 挂死/异常都不允许拖死心跳线：超时或异常返回 None（上层按
        DEFER 处理）；挂死线程为 daemon，随进程退出，不阻塞下轮判定。
        """
        timeout = max(0.1, float(getattr(self._cfg, "inject_judge_timeout_sec", 30.0)))
        box: dict[str, str] = {}

        def _call() -> None:
            try:
                box["raw"] = str(llm.generate_messages(messages))
            except Exception:  # noqa: BLE001
                logger.exception("[HeartbeatCore] 注入判定 LLM 异常，本轮按 DEFER")
                box["error"] = "1"

        t = threading.Thread(target=_call, name="hb-inject-judge", daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            logger.warning(
                "[HeartbeatCore] 注入判定 LLM 超时（%.1fs），本轮按 DEFER", timeout
            )
            return None
        if "error" in box:
            return None
        return box.get("raw", "")
