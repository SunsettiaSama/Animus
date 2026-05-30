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

    @property
    def system_block(self) -> str:
        angle = self.angle.strip()
        angle_line = f"揣摩方向参考：{angle}" if angle else ""
        lines = [
            "【打破沉默·弱社交】",
            f"用户在你上一句之后已静默约 {int(self.elapsed_sec)} 秒，尚未发来新消息。",
            "在 think 里简短揣摩：对方可能在忙、在思考、还是话未说完？是否适合你用一句极短的承接或轻问打破沉默？",
            "约束：最多一句 speak，勿连发、勿说教、勿猜测过度；若无合适开口，[state]finish 且不写 speak。",
        ]
        if angle_line:
            lines.append(angle_line)
        if self.dialogue_compressed.strip():
            lines.append(
                "近期对话摘要（供揣摩）：\n" + self.dialogue_compressed.strip()
            )
        return "\n".join(lines)

    def user_text(self) -> str:
        return f"（系统：用户已静默约 {int(self.elapsed_sec)} 秒，无新消息。）"
