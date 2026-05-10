from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
    from agent.scheduler.heartbeat.config import HeartbeatConfig

logger = logging.getLogger(__name__)

_PRECHECK_SYSTEM = (
    "你是一个调度助手。请检查以下心跳清单，判断当前是否有需要处理的事项。\n"
    "如果没有任何需要处理的事项，只回复：HEARTBEAT_OK\n"
    "如果有需要处理的事项，回复：ESCALATE: <简短说明原因，不超过100字>\n"
    "不要回复其他内容。"
)


class HeartbeatChecker:
    """Two-tier heartbeat checker.

    Tier 1: cheap LLM single call (no TaoLoop, no memory retrieval).
    Tier 2: full SubAgentRunner with scheduler_engine injected (only on ESCALATE).
    """

    def __init__(
        self,
        cfg: HeartbeatConfig,
        llm_service,        # LLMService | None
        llm_cfg_path: str,  # main LLM config path for tier-2
        scheduler_engine,   # SchedulerEngine ref
        scheduler_cfg,      # SchedulerConfig (for profiles + llm_cfg_path)
        journal=None,
        channel_router=None,
    ) -> None:
        self._cfg = cfg
        self._llm_service = llm_service
        self._llm_cfg_path = llm_cfg_path
        self._scheduler_engine = scheduler_engine
        self._scheduler_cfg = scheduler_cfg
        self._journal = journal
        self._channel_router = channel_router

    # ── Tier 1: precheck ─────────────────────────────────────────────────────

    def precheck(self, heartbeat_content: str) -> str:
        """Call cheap LLM once; return 'HEARTBEAT_OK' or 'ESCALATE: <reason>'."""
        llm = self._resolve_precheck_llm()
        if llm is None:
            logger.warning("[HeartbeatChecker] no LLM available for precheck, skipping")
            return "HEARTBEAT_OK"

        messages = [
            SystemMessage(content=_PRECHECK_SYSTEM),
            HumanMessage(content=f"[心跳清单]\n{heartbeat_content}"),
        ]
        response = llm.generate_messages(messages).strip()
        logger.debug("[HeartbeatChecker] precheck response: %r", response[:120])
        return response

    def _resolve_precheck_llm(self):
        if self._llm_service is not None:
            llm = self._llm_service.get_aux_llm(self._cfg.llm_aux_name)
            if llm is not None:
                return llm
        # fallback: instantiate from cfg path directly
        if self._cfg.llm_aux_name and self._cfg.llm_aux_name != "heartbeat":
            return None
        # try main llm_cfg_path
        from config.llm_core.config import LLMConfig
        from infra.llm.llm import LLM
        return LLM(LLMConfig.from_yaml(self._llm_cfg_path))

    # ── Tier 2: escalate ─────────────────────────────────────────────────────

    def run_escalate(self, reason: str, heartbeat_content: str) -> str:
        """Run full SubAgentRunner with scheduler tools injected."""
        from agent.runner import SubAgentRunner
        from agent.profile import SubAgentProfile

        base_profile: SubAgentProfile = (
            self._scheduler_cfg.profiles.get(self._cfg.profile)
            or self._scheduler_cfg.profiles.get("minimal")
            or SubAgentProfile()
        )

        if self._cfg.light_context:
            from agent.scheduler.config import _sub_memory_none
            base_profile = dataclasses.replace(base_profile, memory=_sub_memory_none())

        system_note_parts = [
            p for p in [
                self._scheduler_cfg.scheduler_system_note,
                base_profile.system_note,
            ] if p
        ]
        combined_note = "\n\n".join(system_note_parts)
        profile = dataclasses.replace(base_profile, system_note=combined_note)

        instruction = (
            f"[心跳清单]\n{heartbeat_content}\n\n"
            f"[待处理事项]\n{reason}"
        )

        notify_fn = None
        if self._journal is not None or self._channel_router is not None:
            _journal = self._journal
            _router = self._channel_router

            def notify_fn(title: str, message: str) -> None:
                if _journal is not None:
                    _journal.append_mid_run_message("heartbeat", "心跳反思", title, message)

        runner = SubAgentRunner()
        result = runner.run_sync(
            instruction=instruction,
            profile=profile,
            llm_cfg_path=self._llm_cfg_path,
            scheduler_engine=self._scheduler_engine,
            notify_fn=notify_fn,
        )
        return result.get("answer", "")
