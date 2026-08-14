from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class DynamicLayerMaterials:
    """ComposeManager 只提供可调度材料库存，不做注入决策。"""

    session_id: str
    memory_ids: tuple[str, ...] = ()
    memory_texts: tuple[str, ...] = ()
    share_texts: tuple[str, ...] = ()
    # 导演可见的自身检索（供其决定是否 pass_info）
    director_memory_ids: tuple[str, ...] = ()
    director_memory_texts: tuple[str, ...] = ()
    meta: dict[str, object] = field(default_factory=dict)


ScheduleAction = Literal["keep", "drop"]


@dataclass(frozen=True)
class DynamicLayerSchedule:
    """唯一调度者（Director）的动态层决策。"""

    inject_memory: bool = False
    memory_unit_ids: tuple[str, ...] = ()
    inject_share: bool = False
    share_indices: tuple[int, ...] = ()
    pass_info: bool = False
    reason: str = ""
    source: str = "director"

    def selected_memory_texts(self, materials: DynamicLayerMaterials) -> tuple[str, ...]:
        if not self.inject_memory:
            return ()
        by_id = dict(zip(materials.memory_ids, materials.memory_texts))
        if self.memory_unit_ids:
            return tuple(
                by_id[uid] for uid in self.memory_unit_ids if uid in by_id and by_id[uid].strip()
            )
        return tuple(t for t in materials.memory_texts if t.strip())

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

    def selected_pass_info_texts(self, materials: DynamicLayerMaterials) -> tuple[str, ...]:
        if not self.pass_info:
            return ()
        return tuple(t for t in materials.director_memory_texts if t.strip())
