from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from .io.inbound.ports import SpeakInboundPort
from .io.outbound.ports import SpeakOrchestratorPort, SpeakOutboundPort
from .io.outbound.stream.ports import SpeakStreamPort

if TYPE_CHECKING:
    from .drive import SpeakDriveResult, SpeakDriveSnapshot
    from .llm.engine import SpeakLLMEngine, SpeakLLMResult


class SpeakDrivePort(Protocol):
    """当下态内驱读口：从 presence 状态机读取冲动与分享意愿。"""

    def drive_snapshot(self, session_id: str) -> SpeakDriveSnapshot: ...

    def evaluate_drive(self, session_id: str) -> SpeakDriveResult: ...


class SpeakLLMPort(Protocol):
    """Speak LLM 生成口。"""

    def generate(
        self,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> SpeakLLMResult: ...


class SpeakToolPort(Protocol):
    """Speak 可选语义任务工具口。"""

    def run_semantic_task(
        self,
        instruction: str,
        *,
        session_id: str = "tao",
    ) -> dict[str, Any]: ...


__all__ = [
    "SpeakDrivePort",
    "SpeakInboundPort",
    "SpeakLLMPort",
    "SpeakOrchestratorPort",
    "SpeakOutboundPort",
    "SpeakStreamPort",
    "SpeakToolPort",
]
