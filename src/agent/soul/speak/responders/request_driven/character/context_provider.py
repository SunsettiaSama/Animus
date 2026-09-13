from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from agent.soul.speak.responders.request_driven.character.interaction import (
    export_interaction_record,
)


@dataclass(frozen=True)
class CharacterContextSnapshot:
    """一次生成开拍前的「当下」上下文快照。

    任何生成路径（用户热路径 / 导演预约到点）都必须在开拍前向
    provider 请求一份新快照；预约不得复用预约时刻拼好的旧上下文，
    否则会拿陈旧的待接消息重复作答。
    """

    interaction_record_text: str
    pending_user_text: str
    recent_self_messages: tuple[str, ...]
    plot_position_text: str
    exchange_rounds: int
    last_agent_speak_at: float
    last_user_speak_at: float
    captured_at: float

    @property
    def age_sec(self) -> float:
        return max(0.0, time.time() - self.captured_at)


class CharacterContextProvider:
    """角色上下文唯一出口：生成前向它要最新上下文，而不是自己攒。"""

    def __init__(self, state_store: Any | None = None) -> None:
        self._state_store = state_store

    def snapshot(
        self,
        state: Any,
        *,
        plot_arc: Any | None = None,
        recent_self_n: int = 4,
    ) -> CharacterContextSnapshot:
        rec = export_interaction_record(state)
        recent_self = tuple(
            str(t)[len("你："):]
            for t in rec.recent_turns
            if str(t).startswith("你：")
        )[-max(1, int(recent_self_n)):]
        pending = ""
        if rec.pending_user and rec.last_user_text.strip():
            pending = rec.last_user_text.strip()
        plot_text = ""
        if plot_arc is not None and getattr(plot_arc, "ready", False):
            plot_text = str(plot_arc.render_for_inject() or "").strip()
        return CharacterContextSnapshot(
            interaction_record_text=rec.render_for_character(),
            pending_user_text=pending,
            recent_self_messages=recent_self,
            plot_position_text=plot_text,
            exchange_rounds=int(rec.exchange_rounds or 0),
            last_agent_speak_at=float(rec.last_agent_speak_at or 0.0),
            last_user_speak_at=float(rec.last_user_speak_at or 0.0),
            captured_at=time.time(),
        )
