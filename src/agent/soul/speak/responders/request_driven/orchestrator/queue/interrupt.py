from __future__ import annotations


def summarize_suspended_compose(items: list) -> str:
    if not items:
        return ""
    parts: list[str] = []
    for index, item in enumerate(items, start=1):
        frame = getattr(item, "frame", item)
        summary = getattr(frame, "share_summary", "")
        wants_share = getattr(frame, "wants_share", False)
        label = "share" if wants_share else "compose"
        if summary:
            parts.append(f"{index}.{label}:{summary[:80]}")
        else:
            parts.append(f"{index}.{label}")
    return "；".join(parts)
