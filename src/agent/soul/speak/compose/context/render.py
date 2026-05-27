from __future__ import annotations

_CONTEXT_HEADER = "【当前对话·压缩】"
_CONTEXT_NOTE = (
    "以下为本会话内已蒸馏的上下文摘要（每若干轮压缩为一句），"
    "按时间顺序排列；忠实转述、不加戏；尚未完成蒸馏的最近轮次不在此列。"
)


def render_dialogue_compressed(sentences: list[str]) -> str:
    """将已完成蒸馏的单句摘要渲染为 prompt 块。"""
    lines = [part.strip() for part in sentences if part.strip()]
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return f"{_CONTEXT_HEADER}\n{_CONTEXT_NOTE}\n{body}"


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
