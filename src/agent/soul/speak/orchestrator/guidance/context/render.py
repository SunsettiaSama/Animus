from __future__ import annotations

_DISTILL_HEADER = "【当前对话 · 上下文蒸馏】"
_DISTILL_NOTE = (
    "以下为当前会话内已完成蒸馏的对话摘要（每段一批轮次压缩为一句）；"
    "用于把握已谈过的脉络，勿与下方未蒸馏原文或长期记忆混淆。"
)

_WM_HEADER = "【当前会话 · 工作记忆】"
_WM_NOTE = (
    "以下为当前 generation 内、尚未纳入蒸馏的最近几轮对白原文；"
    "用于接续当下话题，不要逐句复述或当作台词模板。"
)


def render_dialogue_compressed(sentences: list[str]) -> str:
    """内部 probe 用：已完成蒸馏的单句摘要（无 prompt 头）。"""
    lines = [part.strip() for part in sentences if part.strip()]
    if not lines:
        return ""
    return "\n".join(f"- {line}" for line in lines)


def render_dialogue_context_for_prompt(sentences: list[str]) -> str:
    """主接口 system：当前对话上下文蒸馏块。"""
    body = render_dialogue_compressed(sentences)
    if not body:
        return ""
    return "\n".join([_DISTILL_HEADER, _DISTILL_NOTE, body])


def render_recent_turns_for_prompt(
    *,
    generation: int,
    recent_turns: list[tuple[str, str]],
) -> str:
    """主接口 system：最近轮次原文工作记忆（不含已蒸馏摘要）。"""
    recent_parts: list[str] = []
    for user_text, agent_text in recent_turns:
        user = user_text.strip()
        agent = agent_text.strip()
        if user:
            recent_parts.append(f"用户：{user}")
        if agent:
            recent_parts.append(f"我：{agent}")
    if not recent_parts:
        return ""
    sections: list[str] = [
        _WM_HEADER,
        _WM_NOTE,
        f"generation={generation}",
        "最近轮次（原文）：",
        *recent_parts,
    ]
    return "\n".join(sections)


def render_session_working_memory(
    *,
    generation: int,
    distilled: list[str],
    recent_turns: list[tuple[str, str]],
) -> str:
    """兼容：蒸馏块 + 最近轮次块拼接（调试 / 旧 probe）。"""
    distill = render_dialogue_context_for_prompt(distilled)
    recent = render_recent_turns_for_prompt(
        generation=generation,
        recent_turns=recent_turns,
    )
    if distill and recent:
        return f"{distill}\n\n{recent}"
    return distill or recent


def normalize_one_sentence(text: str, *, max_chars: int = 240) -> str:
    """蒸馏结果规范化：仅保留一句。"""
    normalized = text.strip()
    if not normalized:
        return ""
    normalized = normalized.splitlines()[0].strip()
    normalized = " ".join(normalized.split())
    if not normalized:
        return ""
    for sep in ("。", "！", "？", ".", "!", "?"):
        if sep in normalized:
            head, _ = normalized.split(sep, 1)
            normalized = head + sep if sep in "。！？" else head + "."
            break
    normalized = normalized.strip(' "\'')
    if max_chars > 0 and len(normalized) > max_chars:
        normalized = normalized[:max_chars].rstrip()
    return normalized
