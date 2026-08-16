from __future__ import annotations

import re

from ..ports.memory import MemoryUnit

# 检索匹配只认具体输出：用户话 / 角色说出的话 / 导演干预 / 对话轨迹压缩。
# 系统提示词、人格画像永不进入 query 或 staging corpus。
_NOISE_SOURCES = frozenset(
    {
        "persona",
        "portrait",
        "interactor_portrait",
        "persona_portrait",
        "system",
        "system_prompt",
        "prompt",
        "role_system",
        "agent_persona",
        "self_concept",
        "built_profile",
    }
)

_NOISE_TAG_RE = re.compile(
    r"(persona|portrait|system[_\s-]?prompt|self[_\s-]?concept|built_profile)",
    re.IGNORECASE,
)


def is_noise_source(source: str) -> bool:
    key = (source or "").strip().lower()
    if not key:
        return False
    if key in _NOISE_SOURCES:
        return True
    return _NOISE_TAG_RE.search(key) is not None


def is_noise_unit(unit: MemoryUnit, *, kind: str = "") -> bool:
    if is_noise_source(unit.source) or is_noise_source(kind):
        return True
    return not unit.text.strip()


def filter_utterance_units(
    units: list[MemoryUnit],
    *,
    kind: str = "",
) -> list[MemoryUnit]:
    return [unit for unit in units if not is_noise_unit(unit, kind=kind)]


def match_query_from_utterances(*parts: str) -> str:
    """只拼接对话侧具体输出作为检索 query（不含 system/persona）。"""
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return " ".join(cleaned)
