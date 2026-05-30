from __future__ import annotations

import os
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from .types import InitiativeHint

# NOTE: 被动轮内的可选延展；非 agent 主导型主动提问（见 SessionSocialManager）。
_INITIATIVE_PROMPT = (
    "【对话节奏·可选主动】\n"
    "你不必只做被动应答。除回答用户外，若还适合做一句极短的承接、反问或轻量延展，"
    "可在 think 里先判断「本轮是否要主动多开口一句」。\n"
    "- 用户刚抛出明确新话题时：优先简明应答，不必强行主动。\n"
    "- 若仅应答即可：speak 保持简短，[state]finish。\n"
    "- 若适合轻量主动：speak 末尾可加一句自然追问或话题延展（仍保持短，勿抢话）。\n"
    "- 若确有分享冲动且待分享队列非空：可用 [state]share。\n"
    "勿每轮都主动；克制比话多更重要。"
)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


@dataclass
class _InitiativeState:
    last_hint_turn: int = 0
    hints_shown: int = 0


@dataclass
class TurnInitiativeManager:
    """交互轮内：在用户已发消息的 inbound 轮注入「可选多开口」提示。

    仍以应答为主；TODO: 收敛为 agent 引导型主动提问策略。
    """

    cooldown_turns: int = field(default_factory=lambda: _env_int("REACT_SPEAK_INITIATIVE_COOLDOWN", 2))
    max_user_chars: int = field(default_factory=lambda: _env_int("REACT_SPEAK_INITIATIVE_MAX_USER_CHARS", 420))
    hint_probability: float = field(
        default_factory=lambda: _env_float("REACT_SPEAK_INITIATIVE_HINT_PROB", 0.45),
    )
    min_turn_index: int = 2
    _states: dict[str, _InitiativeState] = field(default_factory=dict)
    _rng: Callable[[], float] = field(default_factory=lambda: random.random)

    def clear_session(self, session_id: str) -> None:
        self._states.pop(session_id, None)

    def _state(self, session_id: str) -> _InitiativeState:
        sid = session_id.strip()
        if sid not in self._states:
            self._states[sid] = _InitiativeState()
        return self._states[sid]

    def evaluate(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        mode: str = "inbound",
    ) -> InitiativeHint | None:
        if mode != "inbound":
            return None
        if turn_index < self.min_turn_index:
            return None
        normalized = user_text.strip()
        if len(normalized) > self.max_user_chars:
            return None

        state = self._state(session_id)
        if turn_index - state.last_hint_turn < self.cooldown_turns:
            return None
        if self._rng() > self.hint_probability:
            return None

        state.last_hint_turn = turn_index
        state.hints_shown += 1
        return InitiativeHint(
            text=_INITIATIVE_PROMPT,
            note=f"initiative: hint turn={turn_index}",
        )
