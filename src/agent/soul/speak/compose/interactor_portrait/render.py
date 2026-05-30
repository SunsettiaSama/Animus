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
    """Speak 注入用：不出现 interactor_id / UUID，空字段用「暂无」。"""
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

    lines = [
        "【对话者画像】",
        f"称呼：{display_name}",
        f"特质：{traits}",
    ]
    relation = agent_relation.strip()
    if relation:
        lines.append(f"与你的关系：{relation}")
    impression = recent_impression.strip()
    if impression:
        lines.append(f"近期印象：{impression}")
    return "\n".join(lines)


def render_interactor_portrait_inject(portrait_text: str) -> str:
    text = portrait_text.strip()
    if not text:
        return ""
    if text.startswith("【对话者画像】"):
        return text
    return f"【对话者画像】\n{text}"
