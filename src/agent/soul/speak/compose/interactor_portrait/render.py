from __future__ import annotations


def render_interactor_portrait_inject(portrait_text: str) -> str:
    text = portrait_text.strip()
    if not text:
        return ""
    if text.startswith("【对话者画像】"):
        return text
    return f"【对话者画像】\n{text}"
