from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RetrieveMode(Enum):
    LIGHT = "light"           # 场景1：每轮推理前基础检索
    HEAVY = "heavy"           # 场景2：问题明显依赖历史
    SUPPLEMENT = "supplement" # 场景3：短期/中期无答案时补全
    PROFILE = "profile"       # 场景4：会话启动时检索用户档案
    TIMELINE = "timeline"     # 场景5：时态查询，按 created_at 顺序返回最近条目


@dataclass
class RetrieveRequest:
    query: str
    mode: RetrieveMode
    short_term_context: str = ""
    medium_term_context: str = ""


@dataclass
class RetrieveResult:
    mode: RetrieveMode
    hits: list[str] = field(default_factory=list)
    combined: str = ""

    @property
    def has_result(self) -> bool:
        return bool(self.hits)
