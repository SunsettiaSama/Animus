from __future__ import annotations

import re
from dataclasses import dataclass

from ..protocol.tags import SPEAK_TAG_NAMES

_TAG_ALTERNATION = "|".join(SPEAK_TAG_NAMES)
_TAG_RE = re.compile(rf"\[({_TAG_ALTERNATION}):([^\]]*)\]", re.IGNORECASE)
_LEGACY_ACTION_RE = re.compile(r"^\[action:([^\]]+)\]\s*(.*)$", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class SpeakTagBlock:
    kind: str
    content: str


def iter_tag_blocks(raw: str) -> list[SpeakTagBlock]:
    """按出现顺序解析 speak 标签块；标签间裸文本视为 speak。"""
    normalized = raw.strip()
    if not normalized:
        return []

    blocks: list[SpeakTagBlock] = []
    last_end = 0
    for match in _TAG_RE.finditer(normalized):
        between = normalized[last_end:match.start()].strip()
        if between:
            blocks.append(SpeakTagBlock("speak", between))
        blocks.append(SpeakTagBlock(match.group(1).lower(), match.group(2).strip()))
        last_end = match.end()

    tail = normalized[last_end:].strip()
    if tail:
        blocks.append(SpeakTagBlock("speak", tail))

    if blocks:
        return blocks

    legacy = _LEGACY_ACTION_RE.match(normalized)
    if legacy:
        action = legacy.group(1).strip()
        remainder = legacy.group(2).strip()
        if action:
            blocks.append(SpeakTagBlock("action", action))
        if remainder:
            blocks.append(SpeakTagBlock("speak", remainder))
        return blocks

    return [SpeakTagBlock("speak", normalized)]
