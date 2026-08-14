from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TurnPair:
    user_text: str
    agent_text: str


@dataclass
class TrajectoryStore:
    distilled: list[str] = field(default_factory=list)
    working: list[TurnPair] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)


class TrajectoryCompressor:
    """每 k 轮压缩；输入严格仅 user/agent 回话原文。"""

    def __init__(self, *, chunk_size: int = 4) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size 必须 >= 1")
        self._chunk_size = chunk_size
        self._sessions: dict[str, TrajectoryStore] = {}

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id.strip(), None)

    def store(self, session_id: str) -> TrajectoryStore:
        sid = session_id.strip()
        state = self._sessions.get(sid)
        if state is None:
            state = TrajectoryStore()
            self._sessions[sid] = state
        return state

    def record_turn(self, session_id: str, user_text: str, agent_text: str) -> str | None:
        """记账并在满 k 轮时压缩；返回新摘要或 None。"""
        user = user_text.strip()
        agent = agent_text.strip()
        if not user and not agent:
            return None
        state = self.store(session_id)
        with state.lock:
            state.working.append(TurnPair(user_text=user, agent_text=agent))
            if len(state.working) < self._chunk_size:
                return None
            batch = state.working[: self._chunk_size]
            state.working = state.working[self._chunk_size :]
            summary = _compress_batch(batch, prior=state.distilled)
            state.distilled.append(summary)
            return summary

    def snapshot_texts(self, session_id: str) -> tuple[list[str], list[TurnPair]]:
        state = self.store(session_id)
        with state.lock:
            return list(state.distilled), list(state.working)


def _compress_batch(batch: list[TurnPair], *, prior: list[str]) -> str:
    parts: list[str] = []
    if prior:
        parts.append(prior[-1])
    for pair in batch:
        if pair.user_text:
            parts.append(f"用户：{pair.user_text}")
        if pair.agent_text:
            parts.append(f"你：{pair.agent_text}")
    text = " ".join(parts).strip()
    if len(text) > 240:
        return text[:240]
    return text
