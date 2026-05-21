from __future__ import annotations

from datetime import datetime, timezone

from config.soul.config import SoulConfig
from agent.soul.life.life_bridge import LifeContextInput

from ...anchor.chronicle.entry import AnchorChronicleKind
from ...anchor.chronicle.store import AnchorChronicleStore
from ..chronicle.entry import VirtualChronicleKind
from ..chronicle.store import VirtualChronicleStore


def build_life_context_from_chronicle(
    store: AnchorChronicleStore,
    *,
    virtual_store: VirtualChronicleStore | None = None,
    days: int = 1,
    date_str: str = "",
    salient_threshold: float | None = None,
) -> LifeContextInput:
    threshold = (
        salient_threshold
        if salient_threshold is not None
        else SoulConfig.default().chronicle_salient_threshold
    )
    if not date_str:
        date_str = datetime.now(timezone.utc).date().isoformat()

    anchor_entries = store.recent_days(days)
    virtual_entries = virtual_store.recent_days(days) if virtual_store is not None else []

    event_lines = [
        f"[{e.ts[:16]}] {e.summary}"
        for e in anchor_entries
        if e.summary.strip()
    ]
    event_lines.extend(
        f"[虚拟·{e.ts[:16]}] {e.summary}"
        for e in virtual_entries
        if e.summary.strip()
    )
    event_lines.sort()

    notable_flags: list[str] = []
    for e in anchor_entries:
        if e.salience >= threshold:
            notable_flags.append(f"[高显著性] {e.summary}")
    for e in virtual_entries:
        if e.salience >= threshold:
            notable_flags.append(f"[虚拟·高显著性] {e.summary}")
        if e.kind in (
            VirtualChronicleKind.story_beat,
            VirtualChronicleKind.landmark,
            VirtualChronicleKind.surprise,
            VirtualChronicleKind.wander_beat,
        ):
            notable_flags.append(f"[虚拟] {e.summary}")

    dialogue_count = store.count_kind(AnchorChronicleKind.user_turn, days=7)
    if dialogue_count >= 10:
        story_phase = "深入推进"
    elif dialogue_count >= 3:
        story_phase = "稳定互动"
    elif dialogue_count >= 1:
        story_phase = "初期建立"
    else:
        story_phase = "安静期"

    return LifeContextInput(
        date=date_str,
        event_lines=event_lines,
        story_phase=story_phase,
        notable_flags=notable_flags[:8],
    )
