from __future__ import annotations

import re

# compose 侧成对标签；角色提示里出现会教模型走旧格式。
_COMPOSE_PAIR_RE = re.compile(
    r"\[(think|speak|action|state|recall)\](.*?)\[/\1\]",
    re.IGNORECASE | re.DOTALL,
)
# 万一轨迹里混入交付 HTML，历史只保留对白/姿态正文。
_ROLE_HTML_RE = re.compile(
    r"<(speak\s+context|speak\s+action|body\s+action|ask\s+help)\s*>(.*?)</\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)


def scrub_compose_markup(text: str) -> str:
    """角色可见材料：去掉格式标签，只保留可读正文（对白/动作）。"""
    raw = str(text or "")
    if not raw.strip():
        return ""

    kept: list[str] = []
    cursor = 0
    for match in _COMPOSE_PAIR_RE.finditer(raw):
        gap = raw[cursor : match.start()]
        if gap.strip():
            kept.append(gap.strip())
        kind = match.group(1).lower()
        body = (match.group(2) or "").strip()
        if kind in ("speak", "action") and body:
            kept.append(body)
        cursor = match.end()
    tail = raw[cursor:]
    if tail.strip():
        kept.append(tail.strip())
    interim = "\n".join(kept) if kept else raw

    kept_html: list[str] = []
    cursor = 0
    for match in _ROLE_HTML_RE.finditer(interim):
        gap = interim[cursor : match.start()]
        if gap.strip():
            kept_html.append(gap.strip())
        kind = re.sub(r"\s+", " ", match.group(1).strip().lower())
        body = (match.group(2) or "").strip()
        if kind in ("speak context", "body action") and body:
            kept_html.append(body)
        cursor = match.end()
    tail = interim[cursor:]
    if tail.strip():
        kept_html.append(tail.strip())
    cleaned = "\n".join(kept_html) if kept_html else interim
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
