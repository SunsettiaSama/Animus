from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.memory.domain import EvolutionSource, SocialCoreNode


class CoreEvolver:
    """Core 增量演化：Phase 1 append-only�?""

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
        prefix = core.core_traits.strip()
        entry = f"[{stamp}|{source.value}] {text}"
        core.core_traits = f"{prefix}\n{entry}".strip() if prefix else entry
        core.trait_version += 1
        core.last_evolved_at = datetime.now(timezone.utc)
        core.focus = core.focus or f"对{core.interactor_id}的印�?
        return core
