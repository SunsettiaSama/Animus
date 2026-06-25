from __future__ import annotations

import json
import re

from storyview.store.mysql import StoryStoreBundle
from storyview.types import StatePatch


def parse_state_patch(raw: str) -> StatePatch:
    m = re.search(r"\[STATE_PATCH\](.*?)\[/STATE_PATCH\]", raw, re.DOTALL)
    if m is None:
        return StatePatch()
    token = m.group(1).strip()
    if not token:
        return StatePatch()
    data = json.loads(token)
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
