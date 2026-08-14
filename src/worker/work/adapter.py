"""WorkerAdapter — shields WebUI/service from agent.* vs worker.* import drift."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


EventCallback = Callable[[Any], None]


@dataclass
class WorkerAdapterConfig:
    llm_cfg_path: str
    card_id: str = "executor"
    max_steps: int | None = None


class WorkerAdapter:
    """Minimal execution surface used by WorkerWorkService.

    Live path is worker.runner → worker.engine.tao.
    """

    def __init__(self, cfg: WorkerAdapterConfig) -> None:
        self._cfg = cfg
        self._abort = threading.Event()
        self._active_tao: Any = None
        self._sandbox: Any = None
        self._risk_gate: Any = None

    def bind_runtime(
        self,
        *,
        sandbox: Any = None,
        risk_gate: Any = None,
    ) -> None:
        self._sandbox = sandbox
        self._risk_gate = risk_gate

    def request_abort(self) -> None:
        self._abort.set()
        tao = self._active_tao
        if tao is not None and hasattr(tao, "abort"):
            tao.abort()

    def reset_abort(self) -> None:
        self._abort.clear()
        self._active_tao = None

    def inject_user_text(self, text: str, *, metadata: dict[str, Any] | None = None) -> bool:
        tao = self._active_tao
        if tao is None or not hasattr(tao, "inject_user_text"):
            return False
        tao.inject_user_text(text, metadata=metadata)
        return True

    def run_single_task(
        self,
        instruction: str,
        *,
        event_callback: EventCallback | None = None,
        soul: Any = None,
        agent_state_service: Any = None,
        sandbox: Any = None,
        risk_gate: Any = None,
    ) -> dict[str, Any]:
        """Run one SubAgent-style task synchronously; raise on hard failures."""
        self.reset_abort()
        if self._abort.is_set():
            raise RuntimeError("work aborted before start")

        from worker.profile import SubAgentConfig, SubAgentProfile
        from worker.runner import SubAgentRunner

        sub_cfg = SubAgentConfig(llm_cfg_path=self._cfg.llm_cfg_path)
        profile = sub_cfg.resolve_profile(self._cfg.card_id)
        if self._cfg.max_steps is not None:
            profile = SubAgentProfile(
                max_steps=self._cfg.max_steps,
                memory=profile.memory,
                tool_package=profile.tool_package,
                tools=profile.tools,
                system_note=profile.system_note,
            )

        runner = SubAgentRunner()

        def _wrapped_cb(event: Any) -> None:
            if self._abort.is_set():
                raise RuntimeError("work aborted")
            if event_callback is not None:
                event_callback(event)

        def _on_tao_ready(tao: Any) -> None:
            self._active_tao = tao

        result = runner.run_sync(
            instruction,
            profile,
            self._cfg.llm_cfg_path,
            event_callback=_wrapped_cb,
            soul=soul,
            agent_state_service=agent_state_service,
            sandbox=sandbox if sandbox is not None else self._sandbox,
            risk_gate=risk_gate if risk_gate is not None else self._risk_gate,
            on_tao_ready=_on_tao_ready,
        )
        if self._abort.is_set():
            raise RuntimeError("work aborted")
        return {
            "answer": result.get("answer", ""),
            "step_count": result.get("step_count", 0),
            "steps": result.get("steps", []),
            "steps_log": result.get("steps_log", []),
            "units": result.get("units", []),
            "runner": "worker.sub_agent",
            "card_id": self._cfg.card_id,
        }
