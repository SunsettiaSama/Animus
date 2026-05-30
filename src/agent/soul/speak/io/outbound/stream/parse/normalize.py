from __future__ import annotations

import re

from ..protocol.tags import SPEAK_TAG_NAMES

_TAG_ALT = "|".join(SPEAK_TAG_NAMES)
_HTML_OPEN_RE = re.compile(rf"<({_TAG_ALT})>", re.IGNORECASE)
_HTML_CLOSE_RE = re.compile(rf"</({_TAG_ALT})>", re.IGNORECASE)
_BRACKET_CLOSE_RE = re.compile(rf"\[/(?:{_TAG_ALT})\]", re.IGNORECASE)
_ACTION_MARKER = "（动作）"
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "<" + "/" + "think" + ">"
_REASONING_OPEN = "<" + "redacted_thinking" + ">"
_REASONING_CLOSE = "<" + "/" + "redacted_thinking" + ">"


def _html_open_to_bracket(match: re.Match[str]) -> str:
    return f"[{match.group(1).lower()}]"


def _html_close_to_bracket(match: re.Match[str]) -> str:
    kind = match.group(1).lower()
    if kind in ("redacted_thinking", "think"):
        return "[/think]"
    return f"[/{kind}]"


def _normalize_action_marker_closes(text: str) -> str:
    pattern = re.compile(
        rf"{re.escape(_ACTION_MARKER)}(.*?)</action>",
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub(lambda match: f"[action]{match.group(1).strip()}[/action]", text)


_HYBRID_L1_L2_CLOSE_RE = re.compile(
    rf"\[({_TAG_ALT}):(.+?)\[/(?:\1)\]",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_hybrid_l1_l2_closes(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        body = match.group(2).strip()
        return f"[{kind}]{body}[/{kind}]"

    return _HYBRID_L1_L2_CLOSE_RE.sub(repl, text)


def _normalize_dangling_speak_close(text: str) -> str:
    lowered = text.lower()
    if "</speak>" not in lowered and "[/speak]" not in lowered:
        return text
    if re.search(r"\[speak\]", text, re.IGNORECASE):
        return text
    match = re.search(r"^(.*?)</speak>\s*$", text, re.IGNORECASE | re.DOTALL)
    if match is None:
        return text
    body = match.group(1).strip()
    if not body:
        return text
    return f"[speak]{body}[/speak]"


def normalize_agent_output(raw: str) -> str:
    """将模型常见变体归一为 bracket 成对标签，便于统一解析。"""
    text = raw.replace("\r\n", "\n")
    text = text.replace(_REASONING_OPEN, "[think]")
    text = text.replace(_REASONING_CLOSE, "[/think]")
    text = text.replace(_THINK_OPEN, "[think]")
    text = text.replace(_THINK_CLOSE, "[/think]")
    text = _normalize_action_marker_closes(text)
    text = _HTML_OPEN_RE.sub(_html_open_to_bracket, text)
    text = _HTML_CLOSE_RE.sub(_html_close_to_bracket, text)
    text = re.sub(r"</think>", "[/think]", text, flags=re.IGNORECASE)
    text = _normalize_hybrid_l1_l2_closes(text)
    text = _normalize_dangling_speak_close(text)
    return text


def has_structured_tags(raw: str) -> bool:
    normalized = normalize_agent_output(raw)
    if _HTML_OPEN_RE.search(raw) or _HTML_CLOSE_RE.search(raw):
        return True
    if re.search(rf"\[(?:{_TAG_ALT})(?::|])", normalized, re.IGNORECASE):
        return True
    if _BRACKET_CLOSE_RE.search(normalized):
        return True
    return False
