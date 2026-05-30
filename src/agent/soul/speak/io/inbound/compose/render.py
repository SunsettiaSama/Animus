from __future__ import annotations


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = text.strip()
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars]


def render_presence(
    state,
    *,
    max_chars: int = 600,
) -> str:
    """Presence 当下态：affect / somatic / cognition / perception（不含 expectation）。"""
    if state is None:
        return ""

    labels = (
        ("affect", "情感"),
        ("somatic", "身体"),
    )
    lines: list[str] = [
        "【当下态·状态】",
        "以下为当下身心感知与思维，不含当前对话逐字记录。",
    ]
    for key, label in labels:
        text = getattr(state, key).render()
        if text:
            lines.append(f"{label}：{text}")
    thinking = state.cognition.thinking.strip() if state.cognition is not None else ""
    if thinking:
        lines.append(f"认知：{thinking}")
    perception_text = state.perception.render()
    if perception_text:
        lines.append(f"感知：{perception_text}")
    if len(lines) <= 2:
        return ""
    return _truncate_text("\n".join(lines), max_chars)


render_presence_static = render_presence
