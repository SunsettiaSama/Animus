from __future__ import annotations

import json
import re
from typing import Any

from agent.soul.speak.llm.engine import SpeakLLMEngine

_PICK_SYSTEM = """\
你是场景定位器。根据用户表述，从候选场景列表中选最匹配的一项。
只输出 JSON，不要 markdown：{"index": 0} 或 {"index": null}。
index 为候选下标（从 0 起）；无法判定时填 null。
"""


def _format_candidates(candidates: tuple[Any, ...]) -> str:
    lines: list[str] = []
    for index, candidate in enumerate(candidates):
        scene = candidate.scene
        name = str(getattr(scene, "name", "") or "").strip()
        narrative = str(getattr(scene, "narrative", "") or "").strip()
        transition = str(getattr(candidate, "transition_text", "") or "").strip()
        tags = getattr(scene, "tags", ()) or ()
        tag_text = "、".join(str(tag).strip() for tag in tags if str(tag).strip())
        block = f"[{index}] 名称：{name or '（无名）'}"
        if tag_text:
            block += f"\n标签：{tag_text}"
        if transition:
            block += f"\n转化：{transition}"
        if narrative:
            block += f"\n叙述：{narrative[:120]}"
        lines.append(block)
    return "\n\n".join(lines)


def _parse_index(raw: str, *, limit: int) -> int | None:
    text = raw.strip()
    if not text:
        return None
    match = re.search(r"\{[\s\S]*\}", text)
    payload = match.group(0) if match else text
    data = json.loads(payload)
    if not isinstance(data, dict):
        return None
    index = data.get("index")
    if index is None:
        return None
    if isinstance(index, bool):
        return None
    resolved = int(index)
    if resolved < 0 or resolved >= limit:
        return None
    return resolved


def pick_scene_by_llm(
    engine: SpeakLLMEngine,
    query: str,
    candidates: tuple[Any, ...],
) -> tuple[int | None, str]:
    if engine.llm is None or not candidates:
        return None, ""
    if len(candidates) == 1:
        return 0, "llm_single"
    context = _format_candidates(candidates)
    user_text = f"用户表述：{query.strip()}\n\n候选场景：\n{context}"
    result = engine.generate(user_text, system=_PICK_SYSTEM)
    index = _parse_index(result.text, limit=len(candidates))
    if index is None:
        return None, ""
    return index, "llm"
