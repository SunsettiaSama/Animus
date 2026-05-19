from __future__ import annotations

from enum import Enum


class ExperienceSource(str, Enum):
    """ExperienceUnit.source 约定：编排器据此路由 Chronicle 与碰撞检测。"""

    user = "user"
    interaction = "interaction"
    narrative = "narrative"
    surprise = "surprise"
    collision = "collision"


# 现实锚点层写入编排器的 source
REALITY_SOURCES: frozenset[str] = frozenset({
    ExperienceSource.user.value,
    ExperienceSource.interaction.value,
})

# 虚拟层写入编排器的 source
VIRTUAL_SOURCES: frozenset[str] = frozenset({
    ExperienceSource.narrative.value,
    ExperienceSource.surprise.value,
})

# 参与交会折叠检测的 source（现实 + 虚拟）
COLLISION_SOURCES: frozenset[str] = frozenset({
    ExperienceSource.user.value,
    ExperienceSource.interaction.value,
    ExperienceSource.narrative.value,
    ExperienceSource.surprise.value,
})


def is_reality_source(source: str) -> bool:
    return source in REALITY_SOURCES


def is_virtual_source(source: str) -> bool:
    return source in VIRTUAL_SOURCES


def is_collision_source(source: str) -> bool:
    return source in COLLISION_SOURCES
