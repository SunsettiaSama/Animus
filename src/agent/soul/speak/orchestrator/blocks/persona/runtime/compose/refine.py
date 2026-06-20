from __future__ import annotations

from agent.soul.speak.llm.engine import SpeakLLMEngine

from ..limits import IDENTITY_HARD_MAX_CHARS, clamp_identity_text
from ..prompt_rules import PERSONA_NARRATIVE_REFINE_SYSTEM
from .records import PersonaDistillRecord

_CORE_LABEL = "【核心画像锚点】"
_DYNAMICS_LABEL = "【近期动态】"


def _format_history(records: tuple[PersonaDistillRecord, ...]) -> str:
    if not records:
        return ""
    lines: list[str] = []
    for item in records[-6:]:
        text = item.text.strip()
        if not text:
            continue
        lines.append(f"- turn {item.turn_index} [{item.kind}] {text}")
    if not lines:
        return ""
    return "【过往自叙/蒸馏记录】\n" + "\n".join(lines)


def refine_self_narrative(
    llm: SpeakLLMEngine | None,
    *,
    base_narrative: str,
    stable_portrait: str,
    state_portrait: str,
    injected_context: str = "",
    distill_history: tuple[PersonaDistillRecord, ...] = (),
    hard_max: int = IDENTITY_HARD_MAX_CHARS,
) -> str:
    base = base_narrative.strip()
    if not base:
        raise ValueError("base_narrative 不能为空")

    context = injected_context.strip()
    history = distill_history
    if not context and not history:
        return clamp_identity_text(base, hard_max=hard_max)

    if llm is None:
        merged = base
        if context:
            merged = f"{base} {context}"
        return clamp_identity_text(merged, hard_max=hard_max)

    user_lines = [
        f"{_CORE_LABEL}\n{stable_portrait.strip()}",
        f"【当前自叙草稿】\n{base}",
    ]
    state = state_portrait.strip()
    if state:
        user_lines.append(f"{_DYNAMICS_LABEL}\n{state}")
    hist_block = _format_history(history)
    if hist_block:
        user_lines.append(hist_block)
    if context:
        user_lines.append(f"【本轮上下文（成因依据仅取自此处）】\n{context}")
    user_lines.append(
        "请按 system 要求的顺序修订为一段话：核心画像 → 近期动态 → "
        "（若有依据）最近发生了什么使你变成现在这样。"
    )

    result = llm.generate("\n\n".join(user_lines), system=PERSONA_NARRATIVE_REFINE_SYSTEM)
    refined = clamp_identity_text(result.text, hard_max=hard_max)
    if refined:
        return refined
    return clamp_identity_text(base, hard_max=hard_max)
