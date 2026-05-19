from __future__ import annotations

import dataclasses
from typing import Any

from agent.profile import SubAgentProfile

from .types import TaoRunRequest, TaoRunResult, result_from_runner_dict


class SubAgentTaoBackend:
    """默认 Base Tao 后端：独立 TaoLoop 会话（SubAgentRunner）。"""

    def __init__(
        self,
        llm_cfg_path: str = "config/llm_core/config.yaml",
        profiles: dict[str, SubAgentProfile] | None = None,
        scheduler_engine=None,
        soul=None,
    ) -> None:
        self._llm_cfg_path = llm_cfg_path
        self._profiles = profiles
        self._scheduler_engine = scheduler_engine
        self._soul = soul

    def set_scheduler_engine(self, engine) -> None:
        self._scheduler_engine = scheduler_engine

    def _resolve_profiles(self) -> dict[str, SubAgentProfile]:
        if self._profiles is not None:
            return self._profiles
        from agent.soul.heartbeat.profiles import make_default_scheduler_config
        return make_default_scheduler_config(llm_cfg_path=self._llm_cfg_path).profiles

    def run(self, request: TaoRunRequest) -> TaoRunResult:
        from agent.runner import SubAgentRunner

        profiles = self._resolve_profiles()
        base: SubAgentProfile = (
            profiles.get(request.profile_name)
            or profiles.get("with_memory")
            or profiles.get("minimal")
            or SubAgentProfile()
        )
        note_parts = [p for p in (base.system_note, request.system_note) if p and p.strip()]
        profile = dataclasses.replace(
            base,
            system_note="\n\n".join(note_parts),
        )
        raw = SubAgentRunner().run_sync(
            instruction=request.instruction,
            profile=profile,
            llm_cfg_path=self._llm_cfg_path,
            scheduler_engine=self._scheduler_engine,
            soul=self._soul,
        )
        return result_from_runner_dict(raw)


class AgentServiceTaoBackend:
    """将 Base Tao 请求转发到 AgentService.run_once（与调度器共用 engine）。"""

    def __init__(self, agent_service: Any) -> None:
        self._agent_service = agent_service

    def run(self, request: TaoRunRequest) -> TaoRunResult:
        instruction = request.instruction
        if request.system_note.strip():
            instruction = f"{request.system_note.strip()}\n\n{instruction}"
        raw = self._agent_service.run_once(
            instruction=instruction,
            profile_name=request.profile_name,
            soul=getattr(self._agent_service, "_soul_service", None),
        )
        return result_from_runner_dict(raw)
