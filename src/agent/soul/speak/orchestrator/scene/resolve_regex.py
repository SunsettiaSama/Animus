from __future__ import annotations

import re
from typing import Any


def pick_scene_by_regex(
    query: str,
    candidates: tuple[Any, ...],
) -> tuple[int | None, str]:
    if not candidates:
        return None, ""
    text = query.strip()
    if not text:
        if len(candidates) == 1:
            return 0, "single_empty_query"
        return None, ""

    name_hits: list[int] = []
    for index, candidate in enumerate(candidates):
        scene = candidate.scene
        name = str(getattr(scene, "name", "") or "").strip()
        if name and name in text:
            name_hits.append(index)
    if len(name_hits) == 1:
        return name_hits[0], "regex_name_substr"

    tag_hits: list[int] = []
    for index, candidate in enumerate(candidates):
        scene = candidate.scene
        tags = getattr(scene, "tags", ()) or ()
        for tag in tags:
            needle = str(tag or "").strip()
            if needle and re.search(re.escape(needle), text):
                tag_hits.append(index)
                break
    if len(tag_hits) == 1:
        return tag_hits[0], "regex_tag"

    name_regex_hits: list[int] = []
    for index, candidate in enumerate(candidates):
        scene = candidate.scene
        name = str(getattr(scene, "name", "") or "").strip()
        if name and re.search(re.escape(name), text, re.IGNORECASE):
            name_regex_hits.append(index)
    if len(name_regex_hits) == 1:
        return name_regex_hits[0], "regex_name"

    transition_hits: list[int] = []
    for index, candidate in enumerate(candidates):
        transition = str(getattr(candidate, "transition_text", "") or "").strip()
        if transition and transition in text:
            transition_hits.append(index)
    if len(transition_hits) == 1:
        return transition_hits[0], "regex_transition"

    if len(candidates) == 1:
        score = int(getattr(candidates[0], "score", 0) or 0)
        if score > 0:
            return 0, "regex_high_score_single"

    return None, ""
