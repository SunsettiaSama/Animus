from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agent.soul.memory.domain.enums import MemoryNetwork, MemoryTier, SocialNodeRole
from agent.soul.memory.graph.base_node import BaseNode, node_now

from .portrait import InteractorPortrait


@dataclass(kw_only=True)
class SocialCoreNode(BaseNode):
    """交互者核心画像节点：结构化 portrait + Agent 主观关系描述。"""

    NODE_KIND = "social_core"

    portrait: InteractorPortrait = field(default_factory=InteractorPortrait)
    agent_relation: str = ""
    trait_changelog: str = ""
    trait_version: int = 1
    last_evolved_at: datetime = field(default_factory=node_now)
    node_role: SocialNodeRole = SocialNodeRole.core
    embed_text_cache: str = ""
    embedding: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.social
        self.node_role = SocialNodeRole.core
        self.tier = MemoryTier.long
        if not self.focus:
            name = self.portrait.name.strip()
            self.focus = f"对{name or self.interactor_id}的印象"

    def embed_text(self) -> str:
        chunks = [self.focus]
        portrait_text = self.portrait.render().strip()
        if portrait_text:
            chunks.append(portrait_text)
        if self.agent_relation.strip():
            chunks.append(f"Agent关系：{self.agent_relation.strip()}")
        if self.trait_changelog.strip():
            chunks.append(self.trait_changelog.strip())
        return " ".join(chunks)


@dataclass(kw_only=True)
class SocialNeighborhoodNode(BaseNode):
    """补充信息节点：事件片段、关系说明等，可与 core / 其他 neighborhood 互连。"""

    NODE_KIND = "social_neighborhood"

    label: str = ""
    content: str = ""
    related_interactor_ids: list[str] = field(default_factory=list)
    node_role: SocialNodeRole = SocialNodeRole.neighborhood
    embed_text_cache: str = ""
    embedding: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.social
        self.node_role = SocialNodeRole.neighborhood

    def embed_text(self) -> str:
        chunks = [self.focus, self.label, self.content]
        if self.related_interactor_ids:
            chunks.append("关联交互者：" + "、".join(self.related_interactor_ids))
        return " ".join(c for c in chunks if c and str(c).strip())


SocialNode = SocialCoreNode | SocialNeighborhoodNode
