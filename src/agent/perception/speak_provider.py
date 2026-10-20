# -*- coding: utf-8 -*-
"""游戏材料 Provider：speak ContextProvider 协议（kind="game"）实现。

接入点 ``SpeakService.register_context_provider``（仓库为"游戏内容、
外部世界观"预留的正式封包位）。本 provider 不提案 material_schedule
（材料调度仍由编剧主导），只补剧情/场景文本：

- ``scene_event``：当前现场快照摘要（若编剧侧为空则由游戏侧补位）；
- ``plot_flow_text``：近期游戏亲历事件的自然语言流水。
"""

from __future__ import annotations

from typing import Any

from agent.perception.store import RecentPacketStore


class GameContextProvider:
    """ContextProvider（kind="game"）：把游戏现场作为角色环境材料。"""

    def __init__(
        self,
        store: RecentPacketStore,
        *,
        world_name: str = "星陨之痕",
        within_sec: float = 1800.0,
    ) -> None:
        self._store = store
        self._world_name = world_name
        self._within_sec = within_sec

    @property
    def kind(self) -> str:
        return "game"

    def snapshot(self, session_id: str) -> dict[str, Any]:
        _ = session_id
        scene = self._store.latest_scene()
        packets = self._store.recent_packets(limit=3, within_sec=self._within_sec)
        flow_lines = [p.narrative for p in reversed(packets) if p.narrative]
        scene_text = scene.summary() if scene is not None else ""
        if scene_text:
            scene_text = f"【{self._world_name}】{scene_text}"
        return {
            "kind": self.kind,
            "source": "perception_protocol",
            "material_schedule": {},
            "plot_outline_text": "",
            "plot_flow_text": "\n".join(flow_lines),
            "scene_event": scene_text,
        }
