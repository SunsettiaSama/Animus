from __future__ import annotations

from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.rumination.eligibility import (
    entry_weight,
    is_high_emotion,
    is_ruminatable,
    unfinished_score_of,
)
from agent.soul.memory.rumination.types import RuminationBufferEntry, RuminationConfig


class RuminationBuffer:
    """可能反刍的 graph node id 池；条目须同时满足高情绪与未完成感。"""

    def __init__(self, cfg: RuminationConfig | None = None) -> None:
        self._cfg = cfg or RuminationConfig()
        self._entries: dict[str, RuminationBufferEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def list_ids(self) -> list[str]:
        return list(self._entries.keys())

    def entries(self) -> list[RuminationBufferEntry]:
        return list(self._entries.values())

    def get(self, node_id: str) -> RuminationBufferEntry | None:
        return self._entries.get(node_id)

    def observe(
        self,
        node,
        *,
        tick_id: str = "",
    ) -> bool:
        ok, emotion, unfinished = is_ruminatable(
            node,
            emotion_threshold=self._cfg.emotion_threshold,
            unfinished_threshold=self._cfg.unfinished_threshold,
        )
        if not ok:
            self._entries.pop(node.id, None)
            return False
        self._entries[node.id] = RuminationBufferEntry(
            node_id=node.id,
            emotion_intensity=emotion,
            unfinished_score=unfinished,
            weight=entry_weight(emotion, unfinished),
            tick_id=tick_id,
        )
        self._trim()
        return True

    def observe_high_emotion(
        self,
        node,
        *,
        tick_id: str = "",
        emotion_threshold: float | None = None,
    ) -> bool:
        """睡眠整理等路径：仅高情绪即可入池，不要求未完成感。"""
        threshold = (
            emotion_threshold
            if emotion_threshold is not None
            else self._cfg.emotion_threshold
        )
        ok, emotion = is_high_emotion(node, threshold=threshold)
        if not ok:
            return False
        unfinished = unfinished_score_of(node)
        self._entries[node.id] = RuminationBufferEntry(
            node_id=node.id,
            emotion_intensity=emotion,
            unfinished_score=unfinished,
            weight=entry_weight(emotion, max(unfinished, 0.35)),
            tick_id=tick_id,
        )
        self._trim()
        return True

    def ingest_high_emotion_pool(
        self,
        nodes,
        *,
        tick_id: str = "",
        emotion_threshold: float | None = None,
    ) -> int:
        added = 0
        for node in nodes:
            if self.observe_high_emotion(
                node,
                tick_id=tick_id,
                emotion_threshold=emotion_threshold,
            ):
                added += 1
        return added

    def ingest_pool(
        self,
        nodes,
        *,
        tick_id: str = "",
    ) -> int:
        added = 0
        for node in nodes:
            if self.observe(node, tick_id=tick_id):
                added += 1
        return added

    def reconcile(self, store: GraphNodeStore) -> None:
        for node_id in list(self._entries.keys()):
            node = store.get(node_id)
            if node is None:
                self._entries.pop(node_id, None)
                continue
            self.observe(node, tick_id=self._entries[node_id].tick_id)

    def remove(self, node_id: str) -> None:
        self._entries.pop(node_id, None)

    def decay_and_prune(self, *, decay: float, drop_below: float) -> int:
        pruned = 0
        for node_id in list(self._entries.keys()):
            entry = self._entries[node_id]
            new_weight = entry.weight * decay
            if new_weight < drop_below:
                del self._entries[node_id]
                pruned += 1
                continue
            self._entries[node_id] = RuminationBufferEntry(
                node_id=entry.node_id,
                emotion_intensity=entry.emotion_intensity,
                unfinished_score=entry.unfinished_score,
                weight=new_weight,
                tick_id=entry.tick_id,
            )
        return pruned

    def _trim(self) -> None:
        limit = self._cfg.buffer_max_size
        if len(self._entries) <= limit:
            return
        ranked = sorted(
            self._entries.values(),
            key=lambda e: e.weight,
            reverse=True,
        )
        self._entries = {e.node_id: e for e in ranked[:limit]}
