from __future__ import annotations


def parse_turing_verdict_line(raw: str) -> tuple[str, str]:
    """解析裁决首行 ``AGENT`` / ``NOT_AGENT``�?""
    lines = [ln.strip() for ln in (raw or "").strip().splitlines() if ln.strip()]
    if not lines:
        return "", ""
    head = lines[0].upper().replace(" ", "_")
    reason = ""
    for ln in lines[1:]:
        low = ln.lower()
        if low.startswith("reason:"):
            reason = ln.split(":", 1)[-1].strip()
            break
    if head in ("AGENT", "NOT_AGENT"):
        return head, reason
    if "NOT_AGENT" in head or head == "NOTAGENT":
        return "NOT_AGENT", reason or lines[0]
    if "AGENT" in head:
        return "AGENT", reason or lines[0]
    return "", reason
