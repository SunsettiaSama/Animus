from __future__ import annotations

from typing import Protocol


class ShareHintPort(Protocol):
    def share_query_text(self, session_id: str) -> str: ...


class NullShareHintPort:
    def share_query_text(self, session_id: str) -> str:
        return ""
