from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RoleBlockKind = Literal[
    "speak",
    "think",
    "speak_action",
    "speak_context",
    "body_action",
    "ask_help",
    "note_director",
    "note_screenwriter",
    "unknown",
]

# 角色协议：只认成对标签；残片/裸文本填入 speak 字段，不另造 body。
# <think>（角度型，MiniMax-M3 等推理模型的内置思考块）按协议 think 处理，
# 不落入裸文本——否则推理串会整段漏进对外消息。
_ANY_BLOCK_RE = re.compile(
    r"(?:"
    r"\[think\](.*?)\[/think\]"
    r"|<think\s*>(.*?)</\s*think\s*>"
    r"|<(speak|speak\s+action|speak\s+context|body\s+action|ask\s+help|note\s+director|note\s+screenwriter)\s*>(.*?)</\s*\3\s*>"
    r"|\[(speak_action|speak_context|body_action|think|ask_help|note_director|note_screenwriter)\s*:\s*(.*?)]"
    r")",
    re.IGNORECASE | re.DOTALL,
)

# 未闭合的 <think>（推理被 max_tokens 截断，直到文本末尾都没有闭合标签）：
# 吞到终点——下一个角色标签起点或文本末尾，二者取先；不残留为 speak。
_UNCLOSED_THINK_RE = re.compile(
    r"<think\s*>(?:(?!</think>|<speak\b|\[think\]|\[speak\b).)*\Z",
    re.IGNORECASE | re.DOTALL,
)

_ROLE_TAG_DEBRIS_RE = re.compile(
    r"</?\s*(?:body\s+action|speak(?:\s+action|\s+context)?|think|"
    r"ask\s+help|note\s+director|note\s+screenwriter)\s*>",
    re.IGNORECASE,
)
_COMPOSE_PAIR_RE = re.compile(
    r"\[(think|speak|action|state|recall)\](.*?)\[/\1\]",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RoleBlock:
    kind: RoleBlockKind
    content: str
    raw_tag: str = ""


def strip_role_tag_debris(text: str) -> str:
    """去掉角色协议标签残片，只留可读正文。"""
    cleaned = _ROLE_TAG_DEBRIS_RE.sub("", str(text or ""))
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def strip_model_think(text: str) -> str:
    """剥掉推理模型（MiniMax-M3 等）内置的 <think> 块，含未闭合截断段。"""
    cleaned = str(text or "")
    if "<think" not in cleaned.lower():
        return cleaned
    cleaned = _ANY_BLOCK_RE.sub(
        lambda m: "" if (m.group(1) is not None or m.group(2) is not None) else m.group(0),
        cleaned,
    )
    cleaned = _UNCLOSED_THINK_RE.sub("", cleaned)
    return cleaned.strip()


def parse_role_blocks(raw: str) -> list[RoleBlock]:
    text = raw or ""
    if "<think" in text.lower():
        # 截断兜底：未闭合的推理段整体吞掉（闭合完整的 think 不受影响）。
        text = _UNCLOSED_THINK_RE.sub("", text)
    blocks = list(_scan_any(text))
    if blocks:
        return blocks
    stripped = strip_role_tag_debris(text)
    if not stripped:
        return []
    return [RoleBlock(kind="speak_context", content=stripped, raw_tag="plain")]


def _normalize_tag(tag: str) -> RoleBlockKind:
    key = re.sub(r"\s+", " ", tag.strip().lower())
    if key == "speak":
        return "speak"
    if key in ("think",):
        return "think"
    if key in ("speak context", "speak_context"):
        return "speak_context"
    if key in ("body action", "body_action"):
        return "body_action"
    if key in ("speak action", "speak_action"):
        return "speak_action"
    if key in ("ask help", "ask_help"):
        return "ask_help"
    if key in ("note director", "note_director"):
        return "note_director"
    if key in ("note screenwriter", "note_screenwriter"):
        return "note_screenwriter"
    return "unknown"


def _append_plain_speak(blocks: list[RoleBlock], gap: str) -> None:
    # 间隙里未闭合的 <think>（推理模型截断/忘闭合）：吞到间隙末尾，不落 speak。
    gap = _UNCLOSED_THINK_RE.sub("", gap)
    cleaned = strip_role_tag_debris(gap)
    cleaned = _COMPOSE_PAIR_RE.sub("", cleaned).strip()
    if not cleaned:
        return
    if blocks and blocks[-1].kind == "body_action" and blocks[-1].content == cleaned:
        return
    blocks.append(RoleBlock(kind="speak", content=cleaned, raw_tag="plain"))


def _scan_any(text: str) -> list[RoleBlock]:
    blocks: list[RoleBlock] = []
    cursor = 0
    for match in _ANY_BLOCK_RE.finditer(text):
        _append_plain_speak(blocks, text[cursor : match.start()])
        if match.group(1) is not None:
            content = (match.group(1) or "").strip()
            if content:
                blocks.append(RoleBlock(kind="think", content=content, raw_tag="think"))
        elif match.group(2) is not None:
            # 角度型 <think>…</think>（推理模型内置思考块）
            content = (match.group(2) or "").strip()
            if content:
                blocks.append(RoleBlock(kind="think", content=content, raw_tag="think"))
        elif match.group(3) is not None:
            tag = match.group(3)
            content = (match.group(4) or "").strip()
            blocks.append(RoleBlock(kind=_normalize_tag(tag), content=content, raw_tag=tag))
        elif match.group(5) is not None:
            tag = match.group(5)
            content = (match.group(6) or "").strip()
            blocks.append(RoleBlock(kind=_normalize_tag(tag), content=content, raw_tag=tag))
        cursor = match.end()
    _append_plain_speak(blocks, text[cursor:])
    return blocks
