from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .chunk import SpeakTurnChunk
    from .compose.bundle import SpeakPromptBundle
    from .drive import SpeakDriveResult, SpeakDriveSnapshot
    from .llm.engine import SpeakLLMEngine, SpeakLLMResult
    from .outbound import SpeakRequest
    from .stream.events import SpeakStreamEvent
    from .unit import SpeakAnswer, SpeakExchange


class SpeakInboundPort(Protocol):
    """接收外界话语（用户 → Soul）。"""

    def on_user_text(self, session_id: str, text: str) -> SpeakExchange: ...


class SpeakOutboundPort(Protocol):
    """向外界说话（Soul → 用户）。"""

    def deliver(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> SpeakAnswer: ...


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


class SpeakStreamPort(Protocol):
    """Speak 流式出站订阅口。"""

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None: ...


class SpeakToolPort(Protocol):
    """Speak 可选语义任务工具口。"""

    def run_semantic_task(
        self,
        instruction: str,
        *,
        session_id: str = "tao",
    ) -> dict[str, Any]: ...


class SpeakOrchestratorPort(Protocol):
    """Speak 顶层编排口。"""

    def run_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        stream: bool = False,
        mode: str = "inbound",
    ) -> dict[str, Any]: ...

    def handle_proactive(self, request: SpeakRequest) -> dict[str, Any]: ...
