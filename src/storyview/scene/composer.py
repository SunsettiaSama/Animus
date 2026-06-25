from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from storyview.gm.canon import enforce_canon, lore_context_block
from storyview.network import SceneNetwork, render_scene_inject
from storyview.store.mysql import StoryStoreBundle
from storyview.types import ScenePacket, StoryEventKind
from storyview.worldview import StoryWorldview

_STORY_WORLD_ONLY_RULE = (
    "避免真实世界日期、系统编排术语和格式标签；不要使用类似 6/25、2026、"
    "第1拍、步骤、轮次、NARRATIVE、STATE_PATCH 的表达。"
)

_SCENE_SYSTEM = """\
你是故事世界的场景卡生成器，为主持人提供可操作的硬信息。
规则：
- 只使用提供的设定与 canon，不得编造矛盾细节
- 避免真实世界日期、系统编排术语和格式标签；不要使用类似 6/25、2026、第1拍、步骤、轮次、NARRATIVE、STATE_PATCH 的表达
- 输出短句，冷静、具体，不写文学化修辞
- 只写外部可观察信息，不写角色内心、情绪、感悟
- 必须包含：当前位置状态、可见物、可交互项、限制或风险
- 80~140 字
- 严格输出：

[NARRATIVE]
（场景卡正文）
[/NARRATIVE]"""


def _extract_tag(raw: str, tag: str) -> str:
    m = re.search(rf"\[{tag}\](.*?)\[/{tag}\]", raw, re.DOTALL)
    if m is None:
        return ""
    return m.group(1).strip()


def _strip_output_tags(text: str) -> str:
    cleaned = re.sub(r"\[/?(?:NARRATIVE|STATE_PATCH)\]", "", text)
    return cleaned.strip()


def _clean_story_text(text: str) -> str:
    cleaned = re.sub(r"\b20\d{2}[/-]\d{1,2}[/-]\d{1,2}\b", "某日", text)
    cleaned = re.sub(r"\b\d{1,2}/\d{1,2}\b", "某日", cleaned)
    cleaned = re.sub(r"第\s*\d+\s*拍[:：]?", "", cleaned)
    return _strip_output_tags(cleaned)


class SceneComposer:
    def __init__(
        self,
        stores: StoryStoreBundle,
        llm=None,
        *,
        scene_network: SceneNetwork | None = None,
    ) -> None:
        self._stores = stores
        self._llm = llm
        self._scene_network = scene_network or SceneNetwork(
            stores.scene.nodes,
            stores.scene.edges,
            runtime=stores,
        )

    def open_scene(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
        scene_id: str | None = None,
        transition_text: str = "",
    ) -> tuple[ScenePacket, str]:
        self._stores.world.ensure(world_id)
        runtime = self._stores.runtime.ensure(world_id)
        world_row = self._stores.world.get(world_id) or {}
        canon = self._stores.world.canon_rules(world_id)
        loc_id = runtime.get("current_location_id")
        lore_rows, entities, lore_ids = self._stores.lore.retrieve_for_cue(
            world_id,
            cue,
            current_location_id=loc_id,
        )
        entity_ids = tuple(str(e["id"]) for e in entities)
        world_time = str(runtime.get("world_time") or "")
        if scene_id:
            scene = self._scene_network.get(scene_id)
            if scene is None:
                raise ValueError(f"unknown scene: {scene_id}")
            from storyview.network.render import build_inject_text

            scene_inject = build_inject_text(scene, transition_text=transition_text)
            if scene.location_id:
                loc_id = scene.location_id
        else:
            locate = self._scene_network.locate(world_id, cue)
            scene_inject = render_scene_inject(locate)
            if locate.scene is not None and locate.scene.location_id:
                loc_id = locate.scene.location_id
        scene_text = self._compose_scene(
            world_row=world_row,
            canon=canon,
            cue=cue,
            lore_rows=lore_rows,
            entities=entities,
            world_time=world_time,
            loc_id=loc_id,
            scene_inject=scene_inject,
        )
        event_id = self._stores.events.create_open(
            world_id,
            kind=str(getattr(kind, "value", kind)),
            cue=cue,
            scene_text=scene_text,
        )
        self._stores.runtime.update_snapshot(world_id, scene_text)
        packet = ScenePacket(
            event_id=event_id,
            world_id=world_id,
            scene_text=scene_text,
            location_id=loc_id,
            entity_ids=entity_ids,
            lore_refs=tuple(lore_ids),
            world_time=world_time,
        )
        return packet, scene_text

    def snapshot(self, world_id: str, cue: str = "") -> str:
        self._stores.runtime.ensure(world_id)
        query = cue.strip()
        if query:
            inject = self._scene_network.scene_inject_text(world_id, query)
            if inject.strip():
                return inject.strip()
        if not query:
            locate = self._scene_network.locate(world_id, "")
            inject = render_scene_inject(locate)
            if inject.strip():
                return inject.strip()
            cached = self._stores.runtime.snapshot_text(world_id)
            if cached:
                return cached
        packet, _ = self.open_scene(
            world_id,
            query or "环顾四周",
            kind=StoryEventKind.snapshot,
        )
        return packet.scene_text

    def _compose_scene(
        self,
        *,
        world_row: dict,
        canon: dict,
        cue: str,
        lore_rows: list[dict],
        entities: list[dict],
        world_time: str,
        loc_id: str | None,
        scene_inject: str = "",
    ) -> str:
        if scene_inject.strip() and self._llm is None:
            return enforce_canon(scene_inject.strip()[:400], canon)

        wv = StoryWorldview.from_dict(
            {
                "title": world_row.get("title") or "未命名世界",
                "setting": world_row.get("setting") or "",
                "era": world_row.get("era") or "",
                "tone": world_row.get("tone") or "",
                "canon": canon.get("prefer") or [],
            }
        )
        loc_name = ""
        if loc_id:
            loc = self._stores.lore.get_location(loc_id)
            if loc:
                loc_name = str(loc.get("name") or "")
        context = lore_context_block(lore_rows, entities)
        if self._llm is None:
            if scene_inject.strip():
                return enforce_canon(scene_inject.strip()[:400], canon)
            base = f"你注意到{cue.strip() or '周围'}——"
            if loc_name:
                base = f"你在{loc_name}，{base}"
            if entities:
                names = "、".join(str(e.get("name") or "") for e in entities[:4])
                base = f"{base}这里有{names}。"
            return enforce_canon(base[:220], canon)

        prompt = (
            f"【故事观】\n{wv.render()}\n\n"
            f"【世界时刻】\n{world_time or '（未设定）'}\n\n"
            f"【当前地点】\n{loc_name or '（未指定）'}\n\n"
        )
        if scene_inject.strip():
            prompt += f"【场景网络·检索】\n{scene_inject.strip()}\n\n"
        prompt += (
            f"【检索设定】\n{context}\n\n"
            f"【本拍线索】\n{cue.strip() or '环顾四周'}\n\n"
            "生成给主持人使用的场景卡："
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SCENE_SYSTEM), HumanMessage(content=prompt)]
        ).strip()
        narrative = _clean_story_text(_extract_tag(raw, "NARRATIVE") or raw)
        return enforce_canon(narrative[:280], canon)
