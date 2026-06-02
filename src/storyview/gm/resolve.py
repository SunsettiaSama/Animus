from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from storyview.fate.dice import roll_d100
from storyview.gm.canon import enforce_canon
from storyview.gm.outline import OutlineTracker
from storyview.gm.state_patch import StateApplier, parse_state_patch
from storyview.store.mysql import StoryStoreBundle
from storyview.types import ResolvedOutcome, StatePatch
from storyview.worldview import StoryWorldview

_RESOLVE_SYSTEM = """\
你是故事世界的客观叙事者（GM），用第二人称「你」描述行动结果。
规则：
- 依据命运骰基调决定顺逆，不得脱离给定场景
- 100~180 字
- 严格输出：

[NARRATIVE]
（第二人称结果）
[/NARRATIVE]
[STATE_PATCH]
{"move_to_location_id": null, "entity_deltas": {}, "flags": {}}
[/STATE_PATCH]

STATE_PATCH 仅填写已给出的 entity_id；未知键留空。"""


def _extract_tag(raw: str, tag: str) -> str:
    m = re.search(rf"\[{tag}\](.*?)\[/{tag}\]", raw, re.DOTALL)
    if m is None:
        return ""
    return m.group(1).strip()


class ActionResolver:
    def __init__(self, stores: StoryStoreBundle, llm=None) -> None:
        self._stores = stores
        self._llm = llm
        self._outline = OutlineTracker(stores)
        self._applier = StateApplier(stores)

    def resolve(
        self,
        event_id: str,
        *,
        intent: str,
        agent_narrative: str = "",
        with_dice: bool = True,
    ) -> ResolvedOutcome:
        event = self._stores.events.get(event_id)
        if event is None:
            raise ValueError(f"unknown story event: {event_id}")
        if event.get("status") != "open":
            raise ValueError(f"story event not open: {event_id}")
        world_id = str(event["world_id"])
        scene_text = str(event.get("scene_text") or "")
        dice = roll_d100() if with_dice else None
        deviation, deviation_note = self._outline.check_deviation(world_id, intent)
        world_row = self._stores.world.get(world_id) or {}
        canon = self._stores.world.canon_rules(world_id)
        runtime = self._stores.runtime.get(world_id) or {}
        wv = StoryWorldview.from_dict(
            {
                "title": world_row.get("title") or "",
                "setting": world_row.get("setting") or "",
                "era": world_row.get("era") or "",
                "tone": world_row.get("tone") or "",
                "canon": canon.get("prefer") or [],
            }
        )
        resolution, patch = self._compose_resolution(
            wv=wv,
            canon=canon,
            scene_text=scene_text,
            intent=intent,
            agent_narrative=agent_narrative,
            dice_value=dice.value if dice else 0,
            dice_tendency=dice.tendency if dice else "",
            world_time=str(runtime.get("world_time") or ""),
        )
        self._applier.apply(world_id, patch)
        self._stores.events.mark_resolved(event_id, scene_text)
        self._stores.events.append_log(
            event_id,
            world_id,
            scene_text=scene_text,
            resolution_text=resolution,
            dice_value=dice.value if dice else 0,
            dice_tendency=dice.tendency if dice else "",
            deviation=deviation,
            deviation_note=deviation_note,
            state_patch=patch,
        )
        self._stores.runtime.update_snapshot(world_id, f"{scene_text}\n{resolution}")
        return ResolvedOutcome(
            event_id=event_id,
            world_id=world_id,
            resolution_text=resolution,
            dice_value=dice.value if dice else 0,
            dice_tendency=dice.tendency if dice else "",
            deviation=deviation,
            deviation_note=deviation_note,
            state_patch=patch,
        )

    def push_cue(
        self,
        world_id: str,
        cue: str,
        *,
        from_speak: bool = True,
    ) -> ResolvedOutcome | None:
        text = cue.strip()
        if not text:
            return None
        if not re.search(r"(走向|打开|看看|进入|离开|拿起|询问|对话|吧台|房间|门)", text):
            return None
        from storyview.gm.scene import SceneComposer

        composer = SceneComposer(self._stores, llm=self._llm)
        packet, _ = composer.open_scene(
            world_id,
            text,
            kind="speak_cue",
        )
        return self.resolve(
            packet.event_id,
            intent=text,
            agent_narrative="",
            with_dice=False,
        )

    def _compose_resolution(
        self,
        *,
        wv: StoryWorldview,
        canon: dict,
        scene_text: str,
        intent: str,
        agent_narrative: str,
        dice_value: int,
        dice_tendency: str,
        world_time: str,
    ) -> tuple[str, StatePatch]:
        if self._llm is None:
            base = f"你尝试{intent.strip() or '行动'}——{dice_tendency or '局面缓缓变化'}。"
            return enforce_canon(base[:220], canon), StatePatch()

        dice_section = (
            f"\n【命运骰 d100={dice_value}】\n{dice_tendency}" if dice_value else ""
        )
        prompt = (
            f"【故事观】\n{wv.render()}\n\n"
            f"【世界时刻】\n{world_time or '（未设定）'}\n\n"
            f"【当前客观场景】\n{scene_text}\n\n"
            f"【参与方自叙（第一人称，仅供参考）】\n{agent_narrative.strip() or '（无）'}\n\n"
            f"【行动意图】\n{intent.strip()}"
            f"{dice_section}\n\n"
            "写出第二人称行动结果，并给出 STATE_PATCH："
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_RESOLVE_SYSTEM), HumanMessage(content=prompt)]
        ).strip()
        narrative = _extract_tag(raw, "NARRATIVE") or raw
        patch = parse_state_patch(raw)
        cleaned = enforce_canon(narrative[:280], canon)
        return cleaned, patch
