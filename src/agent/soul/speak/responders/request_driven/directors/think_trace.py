from __future__ import annotations

import threading
from dataclasses import dataclass, field

# 提示词约束：导演交付指令；压缩核心是 think。
# 具体动作步骤：压缩产物只保留 action + result。
DIRECTOR_THINK_COMPRESS_RULES = (
    "导演轨迹的压缩规则：\n"
    "你交付的是导演指令，压缩的重点是 think 部分。\n"
    "如果步骤里包含具体动作，压缩内容写清楚动作和结果。\n"
    "压缩后的产物保留导演的思考和动作结果，台词和人格细节全部留给角色侧处理。"
)


@dataclass(frozen=True)
class DirectorThinkStep:
    think: str = ""
    action: str = ""
    result: str = ""

    def compress_unit(self) -> str:
        action = self.action.strip()
        if action:
            result = self.result.strip()
            if result:
                return f"{action} → {result}"
            return action
        return self.think.strip()


@dataclass
class DirectorThinkStore:
    distilled: list[str] = field(default_factory=list)
    working: list[DirectorThinkStep] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)


class DirectorThinkCompressor:
    """导演动作轨迹压缩：think 为核心；具体动作仅保留 action+result。"""

    def __init__(self, *, chunk_size: int = 4, max_unit_chars: int = 160) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size 必须 >= 1")
        self._chunk_size = chunk_size
        self._max_unit_chars = max(40, max_unit_chars)
        self._sessions: dict[str, DirectorThinkStore] = {}

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id.strip(), None)

    def store(self, session_id: str) -> DirectorThinkStore:
        sid = session_id.strip()
        state = self._sessions.get(sid)
        if state is None:
            state = DirectorThinkStore()
            self._sessions[sid] = state
        return state

    def record(self, session_id: str, step: DirectorThinkStep) -> str | None:
        unit = step.compress_unit()
        if not unit:
            return None
        state = self.store(session_id)
        with state.lock:
            state.working.append(step)
            if len(state.working) < self._chunk_size:
                return None
            batch = state.working[: self._chunk_size]
            state.working = state.working[self._chunk_size :]
            summary = _compress_batch(
                batch,
                prior=state.distilled,
                max_chars=self._max_unit_chars,
            )
            state.distilled.append(summary)
            return summary

    def snapshot_texts(self, session_id: str) -> tuple[list[str], list[DirectorThinkStep]]:
        state = self.store(session_id)
        with state.lock:
            return list(state.distilled), list(state.working)


def _compress_batch(
    batch: list[DirectorThinkStep],
    *,
    prior: list[str],
    max_chars: int,
) -> str:
    parts: list[str] = []
    if prior:
        parts.append(prior[-1])
    for step in batch:
        unit = step.compress_unit()
        if unit:
            parts.append(unit)
    text = " | ".join(parts).strip()
    if len(text) > max_chars:
        return text[:max_chars]
    return text
