from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InitiativeHint:
    """注入 compose 的「可选主动」提示块。"""

    text: str
    note: str = "initiative: hint"


@dataclass(frozen=True)
class SilenceBreakProbe:
    """长时间静默后、随机通过后的探测上下文。"""

    session_id: str
    elapsed_sec: float
    turn_index: int
    dialogue_compressed: str = ""
    roll: float = 0.0
    threshold: float = 0.0


@dataclass
class SilenceBreakDecision:
    """LLM 对是否打破沉默的判定。"""

    should_break: bool = False
    thought: str = ""
    angle: str = ""
    raw: str = ""


@dataclass(frozen=True)
class SilenceBreakTurnSpec:
    """已判定打破沉默时，本轮 compose / user 侧载荷。"""

    session_id: str
    elapsed_sec: float
    angle: str
    thought: str
    dialogue_compressed: str = ""


@dataclass(frozen=True)
class EnterGreetingProbe:
    session_id: str
    elapsed_sec: float
    turn_index: int
    dialogue_compressed: str = ""


@dataclass
class EnterGreetingDecision:
    should_greet: bool = False
    thought: str = ""
    angle: str = ""
    raw: str = ""


@dataclass(frozen=True)
class EnterGreetingTurnSpec:
    session_id: str
    elapsed_sec: float
    angle: str
    thought: str
    dialogue_compressed: str = ""
