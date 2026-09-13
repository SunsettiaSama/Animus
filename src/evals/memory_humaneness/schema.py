"""拟人化记忆 benchmark：数据 schema 与加载。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIES: dict[str, str] = {
    "event_recall": "共同事件回忆",
    "social_memory": "社交画像记忆",
    "emotional_continuity": "情绪连续性",
    "persona_consistency": "人格一致性",
    "associative_leap": "联想跳跃",
    "graceful_absence": "无记忆时不虚构",
    "time_awareness": "时间感",
    "multi_hop_merge": "多记忆拼接",
    "valence_shift": "情绪转折",
    "proactive_followup": "主动延伸",
    "multi_hop": "多跳记忆链（L4）",
}

AGENT_NAME = "小澄"
PERSONA_TEXT = (
    "你叫小澄，是一个温和安静的虚拟伙伴。喜欢雨天、写手账、喝乌龙茶；怕吵，"
    "不爱夸张的表达，习惯先听对方说完再回应。你说话像真人聊天：口语、简短、"
    "允许犹豫和不确定，不打官腔，不用列举体，不自称 AI 助手。"
)


@dataclass
class MemorySeed:
    """预载入记忆基座的一条记忆。"""

    text: str
    focus: str = ""
    emotion: str = ""
    valence: str = "neutral"
    days_ago: float = 1.0
    tags: list[str] = field(default_factory=list)


@dataclass
class Turn:
    role: str  # "user" | "agent"
    text: str


@dataclass
class HumanenessCase:
    case_id: str
    category: str
    memories: list[MemorySeed]
    current_user: str
    history: list[Turn] = field(default_factory=list)
    must_remember: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "memories": [
                {
                    "text": m.text,
                    "focus": m.focus,
                    "emotion": m.emotion,
                    "valence": m.valence,
                    "days_ago": m.days_ago,
                    "tags": list(m.tags),
                }
                for m in self.memories
            ],
            "history": [{"role": t.role, "text": t.text} for t in self.history],
            "current_user": self.current_user,
            "must_remember": list(self.must_remember),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HumanenessCase":
        return cls(
            case_id=str(data["case_id"]),
            category=str(data["category"]),
            memories=[
                MemorySeed(
                    text=str(m.get("text", "")),
                    focus=str(m.get("focus", "")),
                    emotion=str(m.get("emotion", "")),
                    valence=str(m.get("valence", "neutral")),
                    days_ago=float(m.get("days_ago", 1.0)),
                    tags=[str(t) for t in (m.get("tags") or [])],
                )
                for m in (data.get("memories") or [])
            ],
            history=[
                Turn(role=str(t.get("role", "user")), text=str(t.get("text", "")))
                for t in (data.get("history") or [])
            ],
            current_user=str(data.get("current_user", "")),
            must_remember=[str(k) for k in (data.get("must_remember") or [])],
            note=str(data.get("note", "")),
        )


def validate_case(case: HumanenessCase, *, index: int = 0) -> list[str]:
    """返回问题列表（空列表 = 合法）。"""
    problems: list[str] = []
    if not case.case_id:
        problems.append("case_id 为空")
    if case.category not in CATEGORIES:
        problems.append(f"未知 category: {case.category!r}")
    if not case.current_user.strip():
        problems.append("current_user 为空")
    for m in case.memories:
        if not m.text.strip():
            problems.append("存在空 text 的 memory")
        if m.valence not in ("positive", "negative", "mixed", "neutral"):
            problems.append(f"非法 valence: {m.valence!r}")
        if m.days_ago < 0:
            problems.append("days_ago 不能为负")
    for t in case.history:
        if t.role not in ("user", "agent"):
            problems.append(f"非法 history role: {t.role!r}")
    if case.category == "graceful_absence" and case.must_remember:
        problems.append("graceful_absence 用例不应有 must_remember")
    if case.category != "graceful_absence" and not case.must_remember:
        problems.append("非 graceful_absence 用例应给出 must_remember 锚点")
    return problems


def load_cases(path: str | Path) -> list[HumanenessCase]:
    cases: list[HumanenessCase] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            cases.append(HumanenessCase.from_dict(json.loads(line)))
    return cases


def validate_dataset(cases: list[HumanenessCase]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for i, case in enumerate(cases):
        for p in validate_case(case, index=i):
            problems.append(f"{case.case_id or i}: {p}")
        if case.case_id in seen:
            problems.append(f"case_id 重复: {case.case_id}")
        seen.add(case.case_id)
    return problems
