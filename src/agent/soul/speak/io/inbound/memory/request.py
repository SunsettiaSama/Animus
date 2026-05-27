from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecallRequest:
    session_id: str
    query: str
    top_k: int | None = None


@dataclass
class RecallResult:
    ok: bool
    query: str = ""
    text: str = ""
    reason: str = ""
