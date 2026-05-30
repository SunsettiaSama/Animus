from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.memory.domain.enums import EvolutionSource
from agent.soul.memory.graph.networks.social.node import SocialCoreNode


class CoreEvolver:
    """社交核心画像演化：Phase 1 仅在 trait_changelog 末尾追加带时间戳的条目。"""

    def evolve(
        self,
        core: SocialCoreNode,
        *,
        delta: str,
        source: EvolutionSource,
    ) -> SocialCoreNode:
        text = delta.strip()
        if not text:
            return core
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prefix = core.trait_changelog.strip()
        entry = f"[{stamp}|{source.value}] {text}"
        core.trait_changelog = f"{prefix}\n{entry}".strip() if prefix else entry
        core.trait_version += 1
        core.last_evolved_at = datetime.now(timezone.utc)
        core.focus = core.focus or f"对{core.interactor_id}的印象"
        return core
