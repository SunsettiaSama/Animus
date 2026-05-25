from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from config.soul.presence.interface_config import InterfaceReactConfig

from .executor import ReactActionExecutor
from .parser import ReactActionCall, parse_action_field

if TYPE_CHECKING:
    from agent.soul.service import SoulService


@dataclass
class ReactStepResult:
    applied: bool
    session_id: str
    action: str = ""
    observation: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "session_id": self.session_id,
            "action": self.action,
            "observation": self.observation,
            "reason": self.reason,
            "steps": list(self.steps),
        }


class LightweightReactEngine:
    """轻量 ReAct：解析 agent 追加 action 字段并执行，返回 observation。"""

    def __init__(
        self,
        soul: SoulService,
        *,
        cfg: InterfaceReactConfig | None = None,
        executor: ReactActionExecutor | None = None,
    ) -> None:
        self._soul = soul
        self._cfg = cfg or InterfaceReactConfig.default()
        self._executor = executor or ReactActionExecutor(soul, cfg=self._cfg)

    @property
    def config(self) -> InterfaceReactConfig:
        return self._cfg

    @property
    def executor(self) -> ReactActionExecutor:
        return self._executor

    def run_step(
        self,
        session_id: str,
        step: dict[str, Any],
    ) -> ReactStepResult:
        if not self._cfg.enabled:
            return ReactStepResult(
                applied=False,
                session_id=session_id,
                reason="interface react disabled",
            )
        call = parse_action_field(step)
        if call is None:
            return ReactStepResult(
                applied=False,
                session_id=session_id,
                reason="no action field",
            )
        observation = self._executor.execute(session_id, call)
        return ReactStepResult(
            applied=True,
            session_id=session_id,
            action=call.action,
            observation=observation,
        )

    def run_chain(
        self,
        session_id: str,
        steps: list[dict[str, Any]],
    ) -> ReactStepResult:
        if not self._cfg.enabled:
            return ReactStepResult(
                applied=False,
                session_id=session_id,
                reason="interface react disabled",
            )
        limit = max(1, self._cfg.max_steps)
        collected: list[dict[str, Any]] = []
        last: ReactStepResult | None = None
        for step in steps[:limit]:
            result = self.run_step(session_id, step)
            if not result.applied:
                if last is None:
                    return result
                last.steps = collected
                return last
            collected.append({
                "action": result.action,
                "observation": result.observation,
            })
            last = result
        if last is None:
            return ReactStepResult(
                applied=False,
                session_id=session_id,
                reason="empty steps",
            )
        last.steps = collected
        return last

    def parse_action(self, step: dict[str, Any]) -> ReactActionCall | None:
        return parse_action_field(step)
