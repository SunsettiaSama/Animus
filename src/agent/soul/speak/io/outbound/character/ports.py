from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CharacterHelpRequest:
    session_id: str
    goal: str
    user_text: str = ""


@dataclass(frozen=True)
class CharacterHelpResult:
    ok: bool
    observation: str = ""
    reason: str = ""


class CharacterWorkPort(Protocol):
    """角色 → worker 的轻量工作口；只收自然语言目标，不含工具目录。"""

    def run_lightweight(self, request: CharacterHelpRequest) -> CharacterHelpResult: ...


class NoopCharacterWorkPort:
    def run_lightweight(self, request: CharacterHelpRequest) -> CharacterHelpResult:
        del request
        return CharacterHelpResult(ok=False, reason="work_port_unbound")


class CallableCharacterWorkPort:
    """把自然语言目标交给外部 runner（通常是 WorkerAdapter 轻量 profile）。"""

    def __init__(self, runner) -> None:
        self._runner = runner

    def run_lightweight(self, request: CharacterHelpRequest) -> CharacterHelpResult:
        goal = request.goal.strip()
        if not goal:
            return CharacterHelpResult(ok=False, reason="empty_goal")
        payload = self._runner(
            goal,
            session_id=request.session_id,
            user_text=request.user_text,
        )
        if isinstance(payload, CharacterHelpResult):
            return payload
        if isinstance(payload, dict):
            obs = str(payload.get("observation") or payload.get("answer") or "").strip()
            ok = bool(payload.get("ok", bool(obs)))
            return CharacterHelpResult(
                ok=ok,
                observation=obs,
                reason=str(payload.get("reason") or ""),
            )
        text = str(payload or "").strip()
        return CharacterHelpResult(ok=bool(text), observation=text)
