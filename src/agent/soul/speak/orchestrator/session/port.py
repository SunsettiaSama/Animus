from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agent.soul.speak.session.lifecycle.hold.registry import SpeakSessionRegistry


@dataclass(frozen=True)
class SessionComposeSignals:
    """Session 侧编排信号（不含 ContextDistiller 上下文）。"""

    session_id: str
    turn_index: int
    generation: int
    interactor_id: str

    def snapshot(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "generation": self.generation,
            "interactor_id": self.interactor_id,
        }


class SessionComposePort(Protocol):
    """Orchestrator 读取 session 持有态的只读端口。"""

    def signals(self, session_id: str) -> SessionComposeSignals: ...


class RegistrySessionComposePort:
    """SpeakSessionRegistry → SessionComposePort 适配。"""

    def __init__(self, registry: SpeakSessionRegistry) -> None:
        self._registry = registry

    def signals(self, session_id: str) -> SessionComposeSignals:
        resolved = session_id.strip()
        record = self._registry.get(resolved)
        return SessionComposeSignals(
            session_id=resolved,
            turn_index=self._registry.current_turn_index(resolved),
            generation=record.generation,
            interactor_id=self._registry.get_interactor(resolved),
        )
