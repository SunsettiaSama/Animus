from __future__ import annotations

from storyview.scene.cards import cards_from_meta
from storyview.types import SceneEdge
from storyview.types import SceneUnit
from storyview.worldview import StoryWorldview


class WorldviewProvider:
    """包装现有文本 worldview 与 canon 规则，供场景审查/生成使用。"""

    def __init__(
        self,
        stores,
        *,
        worldview: StoryWorldview | None = None,
    ) -> None:
        self._stores = stores
        self._worldview = worldview or StoryWorldview.default()

    def render_worldview(self, world_id: str) -> str:
        row = self._stores.world.get(world_id)
        if row is None:
            return self._worldview.render()
        canon = self._stores.world.canon_rules(world_id)
        wv = StoryWorldview.from_dict(
            {
                "title": row.get("title") or self._worldview.title,
                "setting": row.get("setting") or "",
                "era": row.get("era") or "",
                "tone": row.get("tone") or "",
                "canon": canon.get("prefer") or [],
            }
        )
        return wv.render()

    def canon_rules(self, world_id: str) -> dict[str, list[str]]:
        return self._stores.world.canon_rules(world_id)

    def existing_context(
        self,
        world_id: str,
        *,
        current_scene_id: str | None = None,
        query: str = "",
        include_mutation_actions: bool = False,
    ) -> str:
        scenes: list[SceneUnit] = self._stores.scene.nodes.list_by_world(world_id)
        edges: list[SceneEdge] = self._stores.scene.edges.list_by_world(world_id)
        scene_by_id = {scene.id: scene for scene in scenes}
        lines: list[str] = ["【已有场景】"]
        if not scenes:
            lines.append("（无）")
        else:
            for scene in scenes[:12]:
                tags = "、".join(scene.tags) if scene.tags else "无标签"
                cards = cards_from_meta(scene.meta)
                card_text = "、".join(card.title for card in cards) if cards else "无 cards"
                lines.append(
                    f"- id={scene.id} name={scene.name} tags={tags} "
                    f"cards={card_text} narrative={scene.narrative[:160]}"
                )
        if edges:
            lines.append("【场景网络边】")
            for edge in edges[:24]:
                source = scene_by_id.get(edge.from_scene_id)
                target = scene_by_id.get(edge.to_scene_id)
                source_name = source.name if source is not None else edge.from_scene_id
                target_name = target.name if target is not None else edge.to_scene_id
                lines.append(
                    f"- {source_name}({edge.from_scene_id}) -> "
                    f"{target_name}({edge.to_scene_id}) "
                    f"transition={edge.transition_text} weight={edge.weight}"
                )
        current_id = current_scene_id or self._resolve_current_scene_id(world_id)
        if current_id:
            current = scene_by_id.get(current_id)
            current_name = current.name if current is not None else current_id
            lines.append(f"【当前场景】{current_name}({current_id})")
            neighbor_lines = self._neighbor_lines(current_id, scene_by_id, edges)
            if neighbor_lines:
                lines.append("【当前场景邻近节点】")
                lines.extend(neighbor_lines)
        if query.strip():
            matched = self._search_scene_lines(query, scenes)
            if matched:
                lines.append("【字段/文本检索命中】")
                lines.extend(matched)
        if include_mutation_actions:
            lines.append("【允许的节点修改计划】")
            lines.append("- update_scene：修改已有 scene 的 narrative/tags/cards")
            lines.append("- add_card：给已有 scene 添加 cards")
            lines.append("- update_card：按 card id/title 替换已有 card")
            lines.append("- remove_card：按 card id 删除已有 card")
            lines.append("如需修改，输出 SceneDraft.node_mutations；必须写 scene_id、action、reason。")
        locations = self._list_locations(world_id)
        if locations:
            lines.append("【已有地点】")
            for loc_id, name in locations[:12]:
                lines.append(f"- {name}（{loc_id[:8]}）")
        return "\n".join(lines)

    def scene_network_context(
        self,
        world_id: str,
        *,
        query: str = "",
        current_scene_id: str | None = None,
        include_mutation_actions: bool = False,
    ) -> str:
        return self.existing_context(
            world_id,
            current_scene_id=current_scene_id,
            query=query,
            include_mutation_actions=include_mutation_actions,
        )

    def _resolve_current_scene_id(self, world_id: str) -> str | None:
        runtime = getattr(self._stores, "runtime", None)
        if runtime is not None and hasattr(runtime, "resolve_current_scene_id"):
            return runtime.resolve_current_scene_id(world_id)
        if hasattr(self._stores, "resolve_current_scene_id"):
            return self._stores.resolve_current_scene_id(world_id)
        return None

    def _neighbor_lines(
        self,
        current_id: str,
        scene_by_id: dict[str, SceneUnit],
        edges: list[SceneEdge],
    ) -> list[str]:
        lines: list[str] = []
        for edge in edges:
            if edge.from_scene_id == current_id:
                target = scene_by_id.get(edge.to_scene_id)
                if target is not None:
                    lines.append(
                        f"- out -> {target.name}({target.id}) "
                        f"transition={edge.transition_text} weight={edge.weight}"
                    )
            elif edge.to_scene_id == current_id:
                source = scene_by_id.get(edge.from_scene_id)
                if source is not None:
                    lines.append(
                        f"- in <- {source.name}({source.id}) "
                        f"transition={edge.transition_text} weight={edge.weight}"
                    )
        return lines[:12]

    def _search_scene_lines(
        self,
        query: str,
        scenes: list[SceneUnit],
    ) -> list[str]:
        tokens = [part.strip().lower() for part in query.replace("，", " ").split() if part.strip()]
        if not tokens:
            return []
        lines: list[str] = []
        for scene in scenes:
            haystack = " ".join([scene.name, scene.narrative, " ".join(scene.tags)]).lower()
            if any(token in haystack for token in tokens):
                lines.append(f"- {scene.name}({scene.id}) tags={','.join(scene.tags)}")
            if len(lines) >= 8:
                break
        return lines

    def _list_locations(self, world_id: str) -> list[tuple[str, str]]:
        lore = getattr(self._stores, "lore", None)
        if lore is None or not hasattr(lore, "list_locations"):
            return []
        rows = lore.list_locations(world_id)
        return [
            (str(row.get("id") or ""), str(row.get("name") or ""))
            for row in rows
            if str(row.get("name") or "").strip()
        ]
