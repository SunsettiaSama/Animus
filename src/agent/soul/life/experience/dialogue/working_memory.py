from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from config.soul.presence.config import (
    DIALOGUE_WORKING_MEMORY_MAX_CHUNKS,
    DIALOGUE_WORKING_MEMORY_WINDOW_SEC,
)


def _utc_now(now: datetime | None = None) -> datetime:
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DialogueMemoryChunk:
    """工作记忆单元：一轮 user-agent 对话（verbatim，不蒸馏）。"""

    ts: datetime
    user_text: str
    agent_text: str


@dataclass
class DialogueWorkingMemory:
    """对话工作记忆：仅保留最近窗口/容量内的 verbatim chunk，其余直接抛弃。"""

    window_sec: float = DIALOGUE_WORKING_MEMORY_WINDOW_SEC
    max_chunks: int = DIALOGUE_WORKING_MEMORY_MAX_CHUNKS
    chunks: list[DialogueMemoryChunk] = field(default_factory=list)

    def append_turn(
        self,
        user_text: str,
        agent_text: str,
        *,
        now: datetime | None = None,
    ) -> None:
        user = user_text.strip()
        agent = agent_text.strip()
        if not user and not agent:
            return
        ts = _utc_now(now)
        self.chunks.append(DialogueMemoryChunk(ts=ts, user_text=user, agent_text=agent))
        self.truncate(now=ts)

    def truncate(self, *, now: datetime | None = None) -> None:
        """按时间窗与容量上限直接截断，不做任何摘要/蒸馏。"""
        ts = _utc_now(now)
        cutoff = ts - timedelta(seconds=self.window_sec)
        self.chunks = [chunk for chunk in self.chunks if chunk.ts >= cutoff]
        overflow = len(self.chunks) - self.max_chunks
        if overflow > 0:
            self.chunks = self.chunks[overflow:]

    def render(self, *, now: datetime | None = None) -> str:
        self.truncate(now=now)
        parts: list[str] = []
        for chunk in self.chunks:
            if chunk.user_text:
                parts.append(f"用户：{chunk.user_text}")
            if chunk.agent_text:
                parts.append(f"我：{chunk.agent_text}")
        return "\n".join(parts)

    def is_empty(self, *, now: datetime | None = None) -> bool:
        self.truncate(now=now)
        return not self.chunks

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)
