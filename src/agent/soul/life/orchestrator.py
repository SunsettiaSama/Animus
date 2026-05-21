from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol

from .experience.log import ExperienceLog
from .experience.sources import COLLISION_SOURCES, is_reality_source, is_virtual_source
from .experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)

if TYPE_CHECKING:
    from .experience.collapser import ExperienceCollapser
    from .ports import AnchorChroniclePort, VirtualChroniclePort

_COLLISION_SCAN_LIMIT = 20


class MemoryIngestPort(Protocol):
    """编排器向记忆层写入的抽象接口，由上层 MemoryService 适配实现。"""

    def ingest_experience(self, unit: ExperienceUnit) -> None: ...

    def retract_experience(self, life_event_id: str) -> bool: ...


class ExperienceOrchestrator:
    """体验编排层：热存储 + 记忆擢升 + 交会折叠 + 双 Chronicle 路由。

    Chronicle 路由约定
    ------------------
    - ``source=user``               → 入站链路写 Anchor Chronicle；编排器不写账
    - ``source=narrative/surprise`` → ``virtual_chronicle``
    - ``source=collision``          → 含 user 时写 anchor；纯虚拟交会写 virtual
    """

    def __init__(
        self,
        log: ExperienceLog,
        memory_port: MemoryIngestPort | None = None,
        reality_chronicle: AnchorChroniclePort | None = None,
        virtual_chronicle: VirtualChroniclePort | None = None,
        *,
        anchor_chronicle: AnchorChroniclePort | None = None,
        chronicle_store: AnchorChroniclePort | None = None,
        memory_ingest_threshold: float = 0.5,
        collapser: ExperienceCollapser | None = None,
        collision_window_min: int = 30,
    ) -> None:
        self._log = log
        self._memory_port = memory_port
        self._anchor_chronicle = anchor_chronicle or reality_chronicle or chronicle_store
        self._virtual_chronicle = virtual_chronicle
        self._memory_ingest_threshold = memory_ingest_threshold
        self._collapser = collapser
        self._collision_window_sec = collision_window_min * 60
        self._memory_ingested_ids: set[str] = set()

    @property
    def anchor_chronicle(self) -> AnchorChroniclePort | None:
        return self._anchor_chronicle

    @property
    def reality_chronicle(self) -> AnchorChroniclePort | None:
        return self._anchor_chronicle

    @property
    def virtual_chronicle(self) -> VirtualChroniclePort | None:
        return self._virtual_chronicle

    def set_virtual_chronicle(self, store: VirtualChroniclePort | None) -> None:
        self._virtual_chronicle = store

    def set_collapser(self, collapser: ExperienceCollapser | None) -> None:
        self._collapser = collapser

    def ingest(self, unit: ExperienceUnit) -> None:
        self._log.append(unit)

        partners = self._find_collision_partners(unit)
        if partners:
            self._do_collapse([unit] + partners)
            return

        self._finalize_single(unit)

    def tick(self) -> list[ExperienceUnit]:
        hot = self._log.recent()
        promoted: list[ExperienceUnit] = []
        for unit in hot:
            if unit.source == "collision":
                continue
            if unit.is_salient(self._memory_ingest_threshold) and unit.id not in self._memory_ingested_ids:
                self._promote_to_memory(unit)
                promoted.append(unit)
        self._log.purge_old()
        return promoted

    def _find_collision_partners(self, incoming: ExperienceUnit) -> list[ExperienceUnit]:
        if self._collapser is None:
            return []
        if incoming.source not in COLLISION_SOURCES:
            return []

        other_sources = COLLISION_SOURCES - {incoming.source}
        incoming_ts = _parse_ts(incoming.ts)

        partners: list[ExperienceUnit] = []
        seen_sources: set[str] = {incoming.source}

        candidates = self._log.recent()[-_COLLISION_SCAN_LIMIT:]
        for candidate in reversed(candidates):
            if candidate.id == incoming.id:
                continue
            if candidate.source not in other_sources:
                continue
            if candidate.source in seen_sources:
                continue
            delta = abs((incoming_ts - _parse_ts(candidate.ts)).total_seconds())
            if delta <= self._collision_window_sec:
                partners.append(candidate)
                seen_sources.add(candidate.source)

        return partners

    def _do_collapse(self, units: list[ExperienceUnit]) -> None:
        merged_text = self._collapser.collapse(units)  # type: ignore[union-attr]

        participant_ids = {u.id for u in units}
        self._log.remove_by_ids(participant_ids)
        self._retract_participants_from_memory(units)
        self._retract_chronicles(participant_ids)

        has_user = any(u.source in ("user", "interaction") for u in units)
        user_units = [u for u in units if u.source in ("user", "interaction")]
        ref = user_units[0] if user_units else units[0]
        top = max(units, key=lambda u: u.feeling.salience)

        prior_parts = [
            f"[{u.source}] {(u.situation.perception or u.situation.narration or u.action.content)[:40]}"
            for u in units
        ]

        collision_unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                session_id=ref.situation.session_id,
                turn_index=ref.situation.turn_index,
                narration=merged_text,
                prior_thought="；".join(prior_parts),
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.deciding,
                content=merged_text,
            ),
            feeling=ExperienceFeeling(
                salience=max(u.feeling.salience for u in units),
                emotion_label=top.feeling.emotion_label,
                valence_delta=top.feeling.valence_delta,
                arousal_delta=top.feeling.arousal_delta,
            ),
            source="collision",
        )

        self._log.append(collision_unit)
        self._write_collision_chronicle(collision_unit, merged_text, has_user=has_user)
        if collision_unit.is_salient(self._memory_ingest_threshold):
            self._promote_to_memory(collision_unit)

    def _finalize_single(self, unit: ExperienceUnit) -> None:
        self._route_chronicle(unit)
        if unit.is_salient(self._memory_ingest_threshold):
            self._promote_to_memory(unit)

    def _route_chronicle(self, unit: ExperienceUnit) -> None:
        if is_reality_source(unit.source):
            return
        if is_virtual_source(unit.source):
            self._write_virtual(unit)

    def _write_virtual(self, unit: ExperienceUnit) -> None:
        if self._virtual_chronicle is None:
            return
        from .virtual.chronicle.adapter import virtual_entry_from_unit

        entry = virtual_entry_from_unit(unit)
        if entry is not None:
            self._virtual_chronicle.append(entry)

    def _write_collision_chronicle(
        self,
        unit: ExperienceUnit,
        merged_text: str,
        *,
        has_user: bool,
    ) -> None:
        if has_user:
            if self._anchor_chronicle is None:
                return
            from .anchor.chronicle.entry import AnchorChronicleEntry, AnchorChronicleKind

            self._anchor_chronicle.append(AnchorChronicleEntry(
                kind=AnchorChronicleKind.collision,
                summary=merged_text[:120],
                session_id=unit.situation.session_id,
                turn_index=unit.situation.turn_index,
                emotion_label=unit.feeling.emotion_label,
                salience=unit.feeling.salience,
                experience_id=unit.id,
            ))
            return

        if self._virtual_chronicle is None:
            return
        from .virtual.chronicle.adapter import collision_entry_from_unit

        self._virtual_chronicle.append(
            collision_entry_from_unit(unit, merged_text, virtual_only=True)
        )

    def _retract_chronicles(self, experience_ids: set[str]) -> None:
        if self._anchor_chronicle is not None:
            self._anchor_chronicle.retract_by_experience_ids(experience_ids)
        if self._virtual_chronicle is not None:
            self._virtual_chronicle.retract_by_experience_ids(experience_ids)

    def _promote_to_memory(self, unit: ExperienceUnit) -> None:
        if self._memory_port is None:
            return
        if unit.id in self._memory_ingested_ids:
            return
        self._memory_port.ingest_experience(unit)
        self._memory_ingested_ids.add(unit.id)

    def _retract_participants_from_memory(self, units: list[ExperienceUnit]) -> None:
        if self._memory_port is None:
            return
        retract = getattr(self._memory_port, "retract_experience", None)
        if not callable(retract):
            return
        for u in units:
            if retract(u.id):
                self._memory_ingested_ids.discard(u.id)


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
