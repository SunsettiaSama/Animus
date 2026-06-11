from __future__ import annotations

_PLACEHOLDER = "暂无"


def _traits_line_from_core_traits(core_traits: list[str]) -> str:
    cleaned = [t.strip() for t in core_traits if t.strip()]
    if cleaned:
        return "、".join(cleaned)
    return ""


def render_interactor_portrait_for_prompt(
    *,
    name: str = "",
    core_traits: list[str] | None = None,
    portrait_body: str = "",
    agent_relation: str = "",
    recent_impression: str = "",
) -> str:
    display_name = name.strip() or _PLACEHOLDER
    traits = _traits_line_from_core_traits(list(core_traits or []))
    if not traits:
        body = portrait_body.strip()
        for line in body.splitlines():
            text = line.strip()
            if text.startswith("特质：") or text.startswith("特质:"):
                traits = text.split("：", 1)[-1].split(":", 1)[-1].strip()
                break
    if not traits:
        traits = _PLACEHOLDER

    parts = [f"与你交谈的是{display_name}，特质偏{traits}"]
    relation = agent_relation.strip()
    if relation:
        parts.append(f"你们的关系是{relation.rstrip('。')}")
    impression = recent_impression.strip()
    if impression:
        parts.append(f"近期你对{display_name}的印象是{impression.rstrip('。')}")
    return "；".join(parts) + "。"


def render_interactor_portrait_inject(portrait_text: str) -> str:
    text = portrait_text.strip()
    if not text:
        return ""
    if text.startswith("与你交谈"):
        return text
    return f"与你交谈的是{text.rstrip('。')}。"
