from __future__ import annotations


def format_recall_preview(lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        return ""
    return "\n".join(f"- {line}" for line in cleaned)


def format_interactor_preview(portrait_text: str) -> str:
    return portrait_text.strip()
