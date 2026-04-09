from __future__ import annotations

from config.react.memory.retrieve_config import RetrieveConfig
from react.memory.long_term.retrieve.base import RetrieveMode

# 关键词列表：命中任意一个 → HEAVY 模式
_HISTORY_KEYWORDS: list[str] = [
    # 中文
    "之前", "上次", "上一次", "以前", "记得", "你还记得",
    "我说过", "我提过", "我们讨论过", "那时候", "过去",
    "当时", "我的习惯", "我的偏好", "我喜欢", "我常用",
    "之前那个", "上次那个", "我们之前", "你帮我弄的",
    "那个任务", "之前的任务", "之前的结果",
    # English
    "earlier", "before", "last time", "remember", "previously",
    "as i mentioned", "i said", "my habit", "my preference",
    "you recall", "we discussed", "that task",
]


def detect_mode(
    query: str,
    cfg: RetrieveConfig,
    is_session_start: bool = False,
    short_term_context: str = "",
    medium_term_context: str = "",
) -> RetrieveMode:
    if is_session_start:
        return RetrieveMode.PROFILE

    if _is_history_dependent(query):
        return RetrieveMode.HEAVY

    if _needs_supplement(short_term_context, medium_term_context, cfg.supplement_context_min_len):
        return RetrieveMode.SUPPLEMENT

    return RetrieveMode.LIGHT


def _is_history_dependent(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in _HISTORY_KEYWORDS)


def _needs_supplement(
    short_term_context: str,
    medium_term_context: str,
    min_len: int,
) -> bool:
    combined = (short_term_context + medium_term_context).strip()
    return len(combined) < min_len
