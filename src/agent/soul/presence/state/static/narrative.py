from __future__ import annotations


def normalize_narrative(text: str) -> str:
    return str(text or "").strip()


def compose_narrative(*parts: str) -> str:
    return "\n".join(normalize_narrative(part) for part in parts if normalize_narrative(part))
