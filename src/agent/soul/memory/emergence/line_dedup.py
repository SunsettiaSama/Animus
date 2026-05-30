from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")


def memory_line_body_key(line: str, *, prefix_len: int = 200) -> str:
    """Speak 记忆行去重键：标题后正文归一化前缀（不同 unit 叙事雷同时可合并）。"""
    text = _WS_RE.sub(" ", str(line or "").strip())
    if not text:
        return ""
    if "：" in text:
        body = text.split("：", 1)[1].strip()
    elif ": " in text:
        body = text.split(": ", 1)[1].strip()
    else:
        body = text
    if prefix_len > 0 and len(body) > prefix_len:
        body = body[:prefix_len]
    return body


def dedupe_memory_line_pairs(
    lines: list[str],
    unit_ids: list[str],
    *,
    seen_unit_ids: set[str] | None = None,
    seen_body_keys: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    ids_seen = seen_unit_ids if seen_unit_ids is not None else set()
    keys_seen = seen_body_keys if seen_body_keys is not None else set()
    out_lines: list[str] = []
    out_ids: list[str] = []
    for line, uid in zip(lines, unit_ids):
        uid = str(uid).strip()
        if not uid:
            continue
        if uid in ids_seen:
            continue
        key = memory_line_body_key(line)
        if key and key in keys_seen:
            continue
        ids_seen.add(uid)
        if key:
            keys_seen.add(key)
        out_lines.append(line)
        out_ids.append(uid)
    return out_lines, out_ids
