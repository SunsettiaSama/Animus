from __future__ import annotations

_MEMORY_KIND_PROMPT_LABELS: dict[str, str] = {
    "factual": "涌现的记忆",
    "reconstructive": "重构的记忆",
    "narrative": "叙事的记忆",
    "social_core": "与你对话的TA",
    "social_neighborhood": "和TA相关的事情",
}


def memory_kind_prompt_label(kind: str) -> str:
    key = kind.strip()
    if not key:
        return "记忆"
    return _MEMORY_KIND_PROMPT_LABELS.get(key, key)
