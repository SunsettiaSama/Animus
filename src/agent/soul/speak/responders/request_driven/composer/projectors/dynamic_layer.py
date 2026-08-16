from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class DynamicLayerMaterials:
    """ComposeManager 只提供可调度材料库存，不做注入决策。

    注入决策由编剧写入 plot_flow；导演不得挑选记忆/分享压入角色。
    """

    session_id: str
    memory_ids: tuple[str, ...] = ()
    memory_texts: tuple[str, ...] = ()
    share_texts: tuple[str, ...] = ()
    # 可选背景信息（编剧可决定是否 pass_info）
    director_memory_ids: tuple[str, ...] = ()
    director_memory_texts: tuple[str, ...] = ()
    meta: dict[str, object] = field(default_factory=dict)


ScheduleAction = Literal["keep", "drop"]


@dataclass(frozen=True)
class DynamicLayerSchedule:
    """动态层注入决策：由编剧写入剧情流后解码，供角色本轮一次性消费。"""

    inject_memory: bool = False
    memory_unit_ids: tuple[str, ...] = ()
    inject_share: bool = False
    share_indices: tuple[int, ...] = ()
    pass_info: bool = False
    reason: str = ""
    source: str = "screenwriter"

    def selected_memory_texts(self, materials: DynamicLayerMaterials) -> tuple[str, ...]:
        if not self.inject_memory:
            return ()
        by_id = dict(zip(materials.memory_ids, materials.memory_texts))
        if self.memory_unit_ids:
            return tuple(
                by_id[uid] for uid in self.memory_unit_ids if uid in by_id and by_id[uid].strip()
            )
        return tuple(t for t in materials.memory_texts if t.strip())

    def selected_memory_ids(self, materials: DynamicLayerMaterials) -> tuple[str, ...]:
        """本轮压入角色的记忆 unit id（用于消费记账）。"""
        if not self.inject_memory:
            return ()
        if self.memory_unit_ids:
            allowed = set(materials.memory_ids)
            return tuple(uid for uid in self.memory_unit_ids if uid in allowed)
        return tuple(uid for uid in materials.memory_ids if str(uid).strip())

    def selected_share_texts(self, materials: DynamicLayerMaterials) -> tuple[str, ...]:
        if not self.inject_share or not materials.share_texts:
            return ()
        if self.share_indices:
            out: list[str] = []
            for index in self.share_indices:
                if 0 <= index < len(materials.share_texts):
                    text = materials.share_texts[index].strip()
                    if text:
                        out.append(text)
            return tuple(out)
        return tuple(t for t in materials.share_texts if t.strip())

    def selected_share_indices(self, materials: DynamicLayerMaterials) -> tuple[int, ...]:
        if not self.inject_share or not materials.share_texts:
            return ()
        if self.share_indices:
            return tuple(
                i
                for i in self.share_indices
                if 0 <= int(i) < len(materials.share_texts)
                and str(materials.share_texts[int(i)] or "").strip()
            )
        return tuple(range(len(materials.share_texts)))

    def selected_pass_info_texts(self, materials: DynamicLayerMaterials) -> tuple[str, ...]:
        if not self.pass_info:
            return ()
        return tuple(t for t in materials.director_memory_texts if t.strip())
