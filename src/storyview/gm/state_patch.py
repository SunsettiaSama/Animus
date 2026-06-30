from __future__ import annotations

import json
import re

from storyview.store.mysql import StoryStoreBundle
from storyview.types import StatePatch


def _first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return ""


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _normalize_json_token(text: str) -> str:
    cleaned = _strip_code_fence(text)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"//[^\n\r]*", "", cleaned)
    cleaned = re.sub(r"\bNone\b", "null", cleaned)
    cleaned = re.sub(r"\bTrue\b", "true", cleaned)
    cleaned = re.sub(r"\bFalse\b", "false", cleaned)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return cleaned.strip()


def _fallback_state_patch_dict(text: str) -> dict:
    move_to_location_id = None
    move_match = re.search(
        r'"move_to_location_id"\s*:\s*"((?:[^"\\]|\\.)*)"',
        text,
    )
    if move_match is not None:
        move_to_location_id = bytes(move_match.group(1), "utf-8").decode("unicode_escape")
    elif re.search(r'"move_to_location_id"\s*:\s*null\b', text, re.IGNORECASE):
        move_to_location_id = None
    return {
        "move_to_location_id": move_to_location_id,
        "entity_deltas": {},
        "flags": {},
    }


def _load_state_patch_dict(text: str) -> dict:
    token = _first_json_object(text) or text.strip()
    candidates = [token, _normalize_json_token(token)]
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return _fallback_state_patch_dict(text)


def parse_state_patch(raw: str) -> StatePatch:
    m = re.search(r"\[STATE_PATCH\](.*?)\[/STATE_PATCH\]", raw, re.DOTALL)
    body = m.group(1).strip() if m is not None else raw.strip()
    if not body:
        return StatePatch()
    data = _load_state_patch_dict(body)
    return StatePatch.from_dict(data)


class StateApplier:
    def __init__(self, stores: StoryStoreBundle) -> None:
        self._stores = stores

    def apply(self, world_id: str, patch: StatePatch) -> None:
        move_to_location_id = patch.move_to_location_id
        if patch.move_to_location_id:
            loc = self._stores.lore.get_location(patch.move_to_location_id)
            if loc is None or loc.get("world_id") != world_id:
                move_to_location_id = None
        entity_deltas: dict[str, dict] = {}
        for entity_id, delta in patch.entity_deltas.items():
            ent = self._stores.lore.get_entity(entity_id)
            if ent is None or ent.get("world_id") != world_id:
                continue
            raw = ent.get("state_json")
            if isinstance(raw, str):
                state = json.loads(raw) if raw else {}
            elif isinstance(raw, dict):
                state = dict(raw)
            else:
                state = {}
            valid_delta: dict = {}
            for key in delta:
                if key in state or key in ("active", "visible", "mixing"):
                    valid_delta[key] = delta[key]
            if valid_delta:
                entity_deltas[entity_id] = valid_delta
        sanitized = StatePatch(
            move_to_location_id=move_to_location_id,
            entity_deltas=entity_deltas,
            flags=dict(patch.flags),
        )
        self._stores.runtime.apply_patch(world_id, sanitized)
