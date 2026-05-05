from __future__ import annotations

import threading
import uuid

from delegate.config import DelegateConfig, DelegateProfile
from delegate.result import DelegateResult
from delegate.runner import DelegateRunner


class DelegateManager:
    def __init__(self, cfg: DelegateConfig) -> None:
        self._cfg = cfg
        self._runner = DelegateRunner()
        self._results: dict[str, DelegateResult] = {}
        self._lock = threading.Lock()

    def _resolve_profile(self, profile: str) -> DelegateProfile:
        p = self._cfg.profiles.get(profile)
        if p is None:
            p = self._cfg.profiles.get("minimal")
        if p is None:
            p = DelegateProfile()
        return p

    def delegate(self, instruction: str, profile: str = "minimal") -> str:
        p = self._resolve_profile(profile)
        return self._runner.run_sync(instruction, p, self._cfg.llm_cfg_path)

    def spawn(self, instruction: str, profile: str = "minimal") -> str:
        agent_id = str(uuid.uuid4())
        result = DelegateResult(agent_id=agent_id, status="running")
        with self._lock:
            self._results[agent_id] = result

        p = self._resolve_profile(profile)

        def _run() -> None:
            answer = ""
            error = ""
            status = "done"
            exc_caught: Exception | None = None
            answer_val = ""
            try:
                answer_val = self._runner.run_sync(instruction, p, self._cfg.llm_cfg_path)
            except Exception as exc:
                error = str(exc)
                status = "failed"
            with self._lock:
                r = self._results.get(agent_id)
                if r is not None:
                    r.status = status
                    r.answer = answer_val
                    r.error = error

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return agent_id

    def spawn_all(self, tasks: list[dict]) -> list[str]:
        return [
            self.spawn(t.get("instruction", ""), t.get("profile", "minimal"))
            for t in tasks
        ]

    def get_result(self, agent_id: str) -> DelegateResult:
        with self._lock:
            r = self._results.get(agent_id)
        if r is None:
            return DelegateResult(agent_id=agent_id, status="not_found")
        return r

    def await_agent(self, agent_id: str, timeout: float = 300.0) -> DelegateResult:
        import time
        deadline = time.monotonic() + timeout
        poll = 0.5
        while time.monotonic() < deadline:
            r = self.get_result(agent_id)
            if r.status in ("done", "failed", "not_found"):
                return r
            time.sleep(poll)
            poll = min(poll * 1.5, 5.0)
        r = self.get_result(agent_id)
        r.status = "timeout"
        return r

    def await_all(self, agent_ids: list[str], timeout: float = 300.0) -> list[DelegateResult]:
        import time
        deadline = time.monotonic() + timeout
        pending = set(agent_ids)
        results: dict[str, DelegateResult] = {}

        poll = 0.5
        while pending and time.monotonic() < deadline:
            done_now = set()
            for aid in pending:
                r = self.get_result(aid)
                if r.status in ("done", "failed", "not_found"):
                    results[aid] = r
                    done_now.add(aid)
            pending -= done_now
            if pending:
                time.sleep(poll)
                poll = min(poll * 1.5, 5.0)

        for aid in pending:
            r = self.get_result(aid)
            r.status = "timeout"
            results[aid] = r

        return [results.get(aid, DelegateResult(agent_id=aid, status="not_found")) for aid in agent_ids]


# Backward-compatible alias
SubAgentManager = DelegateManager
