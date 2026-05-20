from __future__ import annotations

from typing import Any, Protocol


class DialoguePort(Protocol):
    """对话通道 — Agent 以自然语言会话与外界交互（占位）。

    与 TaoLoop、WebUI、Bot 等对接；现实锚点的主路径。
    """

    def bind_session(self, session_id: str, channel_id: str = "") -> None: ...

    def ingest_user_message(self, session_id: str, text: str) -> None: ...

    def deliver_agent_message(self, session_id: str, text: str, *, final: bool = True) -> None: ...

    def poll_inbound(self, session_id: str) -> list[dict[str, Any]]: ...
