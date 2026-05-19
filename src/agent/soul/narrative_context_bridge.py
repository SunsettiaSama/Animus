from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.life.narrative_context import NarrativePurpose

if TYPE_CHECKING:
    from agent.soul.life.virtual.layer import VirtualLayer
    from agent.soul.service import SoulService


class SoulNarrativeContextSupplier:
    """经 persona-worker / memory-worker 按任务刷新叙事上下文。"""

    def __init__(self, soul: SoulService) -> None:
        self._soul = soul
        self._cached_revision = ""
        self._cached_portrait_full = ""
        self._cached_portrait_compact = ""

    def _portrait(self, *, compact: bool) -> str:
        revision = self._soul.workers.persona.submit(
            lambda: self._soul.persona.api.portrait_revision()
        ).result()
        cache = self._cached_portrait_compact if compact else self._cached_portrait_full
        if revision != self._cached_revision or not cache:
            text = self._soul.workers.persona.submit(
                lambda: self._soul.persona.api.portrait_for_narrative(
                    max_chars=600 if compact else 900,
                    compact=compact,
                )
            ).result()
            if compact:
                self._cached_portrait_compact = text
            else:
                self._cached_portrait_full = text
            self._cached_revision = revision
        return self._cached_portrait_compact if compact else self._cached_portrait_full

    def _continuity(self, query: str) -> list[str]:
        q = query.strip()
        if not q:
            return []
        result = self._soul.workers.memory.submit(
            lambda: self._soul.memory.api.continuity_for_narrative(q)
        ).result()
        return list(result)

    def refresh(
        self,
        layer: VirtualLayer,
        purpose: NarrativePurpose,
        *,
        query: str = "",
    ) -> None:
        if purpose == NarrativePurpose.compose:
            layer.apply_narrative_context(
                portrait=self._portrait(compact=False),
                continuity=[],
            )
            return

        compact = purpose in (
            NarrativePurpose.fill,
            NarrativePurpose.surprise,
            NarrativePurpose.fabricate,
        )
        continuity_query = query.strip()
        if purpose == NarrativePurpose.surprise and not continuity_query:
            continuity_query = "意外 自发 内在体验"
        layer.apply_narrative_context(
            portrait=self._portrait(compact=compact),
            continuity=self._continuity(continuity_query),
        )
