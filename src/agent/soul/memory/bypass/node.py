from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.soul.memory.domain import MemoryNetwork
from agent.soul.memory.graph.base_node import BaseNode


@dataclass(kw_only=True)
class StackMemoryUnit(BaseNode):
    """旁路 stack 记忆单元：与 event/social 网完全隔离的追加式记忆条目。

    只存在于旁路自己的 ``StackMemoryStore``，永不进入共享 node/edge store，
    也不会被 event/social 检索命中；仅实现 ``MemoryBasePort`` 检索协议。
    """

    NODE_KIND = "stack"

    content: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.stack

    def embed_text(self) -> str:
        chunks = [self.focus, self.content]
        if self.tags:
            chunks.append(" ".join(self.tags))
        return " ".join(c for c in chunks if c and str(c).strip())

    def to_dict(self) -> dict:
        return {
            "memory_type": self.NODE_KIND,
            "id": self.id,
            "network": self.network.value,
            "interactor_id": self.interactor_id,
            "focus": self.focus,
            "content": self.content,
            "tags": list(self.tags),
            "emotion": self.emotion,
            "emotion_intensity": self.emotion_intensity,
            "valence": self.valence.value,
            "tier": self.tier.value,
            "base_activation": self.base_activation,
            "recall_count": self.recall_count,
            "last_accessed": self.last_accessed.isoformat(),
            "created_at": self.created_at.isoformat(),
            "meta": dict(self.meta or {}),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StackMemoryUnit":
        from agent.soul.memory.domain import MemoryTier, Valence
        from agent.soul.memory.graph.base_node import node_now
        def _dt(key: str) -> datetime:
            raw = str(data.get(key) or "")
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                return node_now()
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        return cls(
            id=str(data.get("id") or ""),
            focus=str(data.get("focus") or ""),
            content=str(data.get("content") or ""),
            tags=[str(t) for t in (data.get("tags") or [])],
            emotion=str(data.get("emotion") or ""),
            emotion_intensity=float(data.get("emotion_intensity") or 0.0),
            valence=Valence(str(data.get("valence") or "neutral")),
            tier=MemoryTier(str(data.get("tier") or "short_term")),
            base_activation=float(data.get("base_activation") or 0.5),
            recall_count=int(data.get("recall_count") or 0),
            last_accessed=_dt("last_accessed"),
            created_at=_dt("created_at"),
            interactor_id=str(data.get("interactor_id") or ""),
            meta=dict(data.get("meta") or {}),
        )
