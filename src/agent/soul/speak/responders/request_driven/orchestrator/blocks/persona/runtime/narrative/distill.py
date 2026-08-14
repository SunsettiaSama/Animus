from __future__ import annotations

from agent.soul.speak.llm.engine import SpeakLLMEngine

from ..limits import NARRATIVE_HARD_MAX_CHARS, clamp_identity_text
from ..prompt_rules import PERSONA_NARRATIVE_COMPOSE_SYSTEM

_CORE_LABEL = "【核心画像】"
_DYNAMICS_LABEL = "【近期动态】"


def _fallback_merge(
    stable_portrait: str,
    state_portrait: str,
    *,
    hard_max: int,
) -> str:
    stable = stable_portrait.strip()
    state = state_portrait.strip()
    if state:
        return clamp_identity_text(f"{stable} {state}", hard_max=hard_max)
    return clamp_identity_text(stable, hard_max=hard_max)


def normalize_self_narrative(
    text: str,
    *,
    hard_max: int = NARRATIVE_HARD_MAX_CHARS,
) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    normalized = normalized.splitlines()[0].strip()
    normalized = " ".join(normalized.split())
    return clamp_identity_text(normalized, hard_max=hard_max)


def distill_self_narrative(
    llm: SpeakLLMEngine | None,
    *,
    stable_portrait: str,
    state_portrait: str,
    hard_max: int = NARRATIVE_HARD_MAX_CHARS,
) -> str:
    stable = stable_portrait.strip()
    state = state_portrait.strip()
    if not stable:
        raise ValueError("stable_portrait 不能为空")

    if llm is None:
        return _fallback_merge(stable, state, hard_max=hard_max)

    user_lines = [f"{_CORE_LABEL}\n{stable}"]
    if state:
        user_lines.append(f"{_DYNAMICS_LABEL}\n{state}")
    user_lines.append(
        "请按 system 要求的顺序输出一段话：核心画像 → 近期动态 → "
        "（若有依据）最近发生了什么使你变成现在这样。"
    )
    result = llm.generate("\n\n".join(user_lines), system=PERSONA_NARRATIVE_COMPOSE_SYSTEM)
    narrative = normalize_self_narrative(result.text, hard_max=hard_max)
    if narrative:
        return narrative
    return _fallback_merge(stable, state, hard_max=hard_max)
