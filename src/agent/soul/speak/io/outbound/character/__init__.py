from __future__ import annotations

from .ports import (
    CallableCharacterWorkPort,
    CharacterHelpRequest,
    CharacterHelpResult,
    CharacterWorkPort,
    NoopCharacterWorkPort,
)


class CharacterWorkGateway:
    """角色求助分流：只转发自然语言目标，绝不把 action/工具目录回注角色。"""

    def __init__(self, port: CharacterWorkPort | None = None) -> None:
        self._port: CharacterWorkPort = port or NoopCharacterWorkPort()

    def bind(self, port: CharacterWorkPort) -> None:
        self._port = port

    def request_help(
        self,
        *,
        session_id: str,
        goal: str,
        user_text: str = "",
    ) -> CharacterHelpResult:
        return self._port.run_lightweight(
            CharacterHelpRequest(
                session_id=session_id.strip(),
                goal=goal.strip(),
                user_text=user_text,
            )
        )

    def request_helps(
        self,
        *,
        session_id: str,
        goals: tuple[str, ...] | list[str],
        user_text: str = "",
        limit: int = 1,
    ) -> tuple[str, ...]:
        """每轮最多处理 limit 条；返回可注入动态层的观察文本。"""
        out: list[str] = []
        cap = max(0, int(limit))
        for goal in goals:
            if len(out) >= cap:
                break
            text = str(goal or "").strip()
            if not text:
                continue
            result = self.request_help(
                session_id=session_id,
                goal=text,
                user_text=user_text,
            )
            if result.ok and result.observation.strip():
                out.append(result.observation.strip())
        return tuple(out)


__all__ = [
    "CallableCharacterWorkPort",
    "CharacterHelpRequest",
    "CharacterHelpResult",
    "CharacterWorkGateway",
    "CharacterWorkPort",
    "NoopCharacterWorkPort",
]
