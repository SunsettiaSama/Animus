from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.heartbeat.inject_mailbox import (
    HeartbeatInjectMailbox,
    get_heartbeat_mailbox,
    set_global_mailbox,
)
from agent.soul.heartbeat.tick_log import HeartbeatTickResult
from runtime.scheduler.heartbeat_config import HeartbeatConfig

if TYPE_CHECKING:
    from agent.soul.heartbeat.module import HeartbeatModule

logger = logging.getLogger(__name__)

_AGENT_INJECT_SYSTEM = (
    "你是一个调度提示助手。根据下面的「心跳待注入摘要」，判断此时是否适合把该摘要并入用户下一轮对话的系统层附注。\n"
    "仅回复一行，且只能是 INJECT 或 DEFER 之一，不要其它文字。\n"
    "若当前适合注入（例如有待办需要用户感知），回复 INJECT；若应等待更适合的时机，回复 DEFER。"
)


def _effective_inject_window(cfg: HeartbeatConfig) -> tuple[str, str, str]:
    start = cfg.inject_window_start or cfg.active_hours_start
    end = cfg.inject_window_end or cfg.active_hours_end
    tz = cfg.inject_timezone or cfg.active_timezone
    return start, end, tz


def _within_window(start_str: str, end_str: str, tz_name: str) -> bool:
    if not start_str or not end_str:
        return True
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz).time()
    start = dtime.fromisoformat(start_str)
    end_ = dtime.fromisoformat(end_str)
    return start <= now_local <= end_


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
        self._cfg: HeartbeatConfig = heartbeat._cfg
        self._llm_service = llm_service
        self._llm_cfg_path = llm_cfg_path
        self._mailbox = mailbox or HeartbeatInjectMailbox()
        self._register_global = register_global_mailbox
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._deferred: str | None = None
        self._deferred_lock = threading.Lock()

    @property
    def mailbox(self) -> HeartbeatInjectMailbox:
        return self._mailbox

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
        logger.info(
            "[HeartbeatCore] started — poll=%ds mode=%s",
            self._cfg.core_service_poll_interval_sec,
            self._cfg.inject_window_mode,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30.0)
            self._thread = None
        if self._register_global and get_heartbeat_mailbox() is self._mailbox:
            set_global_mailbox(None)
        logger.info("[HeartbeatCore] stopped")

    def _run(self) -> None:
        interval = max(5, int(self._cfg.core_service_poll_interval_sec))
        while not self._stop.is_set():
            if self._stop.wait(timeout=interval):
                break
            self._iteration()

    def _iteration(self) -> None:
        self._flush_deferred_if_due()
        self._maybe_preflight()
        result = self._heartbeat.tick()
        text = self._payload_from_result(result)
        if not text:
            return
        window_ok = self._within_inject_window()
        if not window_ok:
            with self._deferred_lock:
                self._deferred = text
            logger.debug("[HeartbeatCore] inject deferred — outside user inject window")
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
                logger.debug("[HeartbeatCore] inject deferred — agent chose DEFER")
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
        logger.debug("[HeartbeatCore] flushed deferred inject")

    def _within_inject_window(self) -> bool:
        start, end, tz = _effective_inject_window(self._cfg)
        return _within_window(start, end, tz)

    def _payload_from_result(self, result: HeartbeatTickResult) -> str:
        if result.outcome == "skip":
            return ""
        return (result.detail_for_inject or "").strip()

    def _maybe_preflight(self) -> None:
        raw = (self._cfg.preflight_instruction or "").strip()
        if not raw:
            return
        engine = self._heartbeat._checker._scheduler_engine
        if engine is None:
            logger.warning("[HeartbeatCore] preflight skipped — scheduler_engine not wired")
            return
        from agent.profile import SubAgentProfile
        from agent.runner import SubAgentRunner

        base = (
            self._heartbeat._checker._scheduler_cfg.profiles.get("minimal")
            or SubAgentProfile()
        )
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
        raw = llm.generate_messages(messages).strip().upper()
        toks = raw.split()
        head = toks[0] if toks else ""
        if head == "DEFER" or raw.startswith("DEFER"):
            return False
        return head == "INJECT" or raw.startswith("INJECT")
