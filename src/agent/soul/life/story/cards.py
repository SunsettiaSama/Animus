"""life.story.cards — 剧情卡片仓（R8：双段结构 + 进度实时同步）。

- **大纲段冻结**：``open`` 时落定 outline，之后不可改（StoryCard 为 frozen
  dataclass，进度更新产生新实例，outline 原样携带）；
- **进度段实时**：``advance`` 更新 current/upcoming 并经总线发 ``StoryProgressSync``
  （无 ack、可丢可合并——同步通道在 bus 层）；
- upcoming 是**预告不是承诺**：允许后续 advance 任意改写（导演重估后整卡重算）。
"""
from __future__ import annotations

import logging
from typing import Callable, Iterable

from agent.soul.storybus import StoryCard, StoryProgressSync

logger = logging.getLogger(__name__)


class StoryCardStore:
    """卡片注册表 + 进度同步发射器（life 侧持有）。"""

    def __init__(self, sync: Callable[[StoryProgressSync], None]) -> None:
        self._sync = sync
        self._cards: dict[str, StoryCard] = {}

    # ── 查询 ───────────────────────────────────────────────────────────────
    def get(self, card_id: str) -> StoryCard | None:
        return self._cards.get(str(card_id or "").strip())

    def list_cards(self) -> list[StoryCard]:
        return list(self._cards.values())

    # ── 写入 ───────────────────────────────────────────────────────────────
    def open(self, outline: str, *, card_id: str | None = None) -> StoryCard:
        """开卡：大纲段落定（冻结）；进度段从空开始。"""
        outline = str(outline or "").strip()
        if not outline:
            raise ValueError("story card outline must not be empty")
        cid = str(card_id or "").strip() or StoryCard.new_id()
        if cid in self._cards:
            raise ValueError(f"story card already open: {cid}")
        card = StoryCard(card_id=cid, outline=outline, current="", upcoming=())
        self._cards[cid] = card
        logger.info("[story.cards] open %s (outline %d chars)", cid, len(outline))
        return card

    def advance(
        self,
        card_id: str,
        *,
        current: str,
        upcoming: Iterable[str] = (),
    ) -> StoryProgressSync | None:
        """推进进度段并发射 ProgressSync；未开卡返回 None。

        一致性约定（协议 §7.3）：应在相关 beat ``performed`` ack 之后调用，
        保证"演过的"与"推进的"一致。
        """
        card = self.get(card_id)
        if card is None:
            logger.debug("[story.cards] advance on unknown card: %s", card_id)
            return None
        updated = StoryCard(
            card_id=card.card_id,
            outline=card.outline,                       # 冻结段原样携带
            current=str(current or ""),
            upcoming=tuple(upcoming),
        )
        self._cards[card.card_id] = updated
        sync = StoryProgressSync(
            card_id=card.card_id,
            current=updated.current,
            upcoming=updated.upcoming,
        )
        self._sync(sync)
        return sync
