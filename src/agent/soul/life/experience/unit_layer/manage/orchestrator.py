from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.soul.life.experience.domain.sources import COLLISION_SOURCES, is_reality_source, is_virtual_source
from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from config.soul.presence.config import (
    EXPERIENCE_COLLISION_SCAN_LIMIT,
    EXPERIENCE_COLLISION_WINDOW_MIN,
)

from ..promote.dispatch import promote_unit_to_memory
from ..promote.ports import MemoryIngestPort
from .log import ExperienceLog

if TYPE_CHECKING:
    from .collapser import ExperienceCollapser
    from agent.soul.life.ports import AnchorChroniclePort, VirtualChroniclePort


class ExperienceUnitManager:
    """单元管理：热存储 + Chronicle 路由 + 交会折叠；入库后委托 ``unit_layer.promote`` 擢升。

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
        memory_ingest_threshold: float | None = None,
        collapser: ExperienceCollapser | None = None,
        collision_window_min: int = EXPERIENCE_COLLISION_WINDOW_MIN,
    ) -> None:
        self._log = log
        self._memory_port = memory_port
        self._anchor_chronicle = anchor_chronicle or reality_chronicle or chronicle_store
        self._virtual_chronicle = virtual_chronicle
        _ = memory_ingest_threshold
        self._collapser = collapser
        self._collision_window_sec = collision_window_min * 60
        self._memory_ingested_ids: set[str] = set()
        self._after_ingest: Callable[[ExperienceUnit], None] | None = None

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

    def set_after_ingest(self, handler: Callable[[ExperienceUnit], None] | None) -> None:
        self._after_ingest = handler

    def promote_unit(self, unit: ExperienceUnit) -> None:
        """单元擢升入口 → ``promote_unit_to_memory`` → ``life.io.memory``。"""
        self._promote_to_memory(unit)

    def ingest_authored_unit(self, unit: ExperienceUnit) -> None:
        """Skill1 产出：热日志 + chronicle + 立即正式擢升 Memory（无会话 buffer）。"""
        self._log.append(unit)
        self._stamp_presence_bundle_on_unit(unit)
        self._route_chronicle(unit)
        self._promote_to_memory(unit)
        self._notify_after_ingest(unit)

    def buffer_authored_unit(self, unit: ExperienceUnit) -> None:
        self.ingest_authored_unit(unit)

    def mark_memory_promoted(self, unit_id: str) -> None:
        if unit_id.strip():
            self._memory_ingested_ids.add(unit_id.strip())

    def ingest_dialogue_close(self, unit: ExperienceUnit) -> None:
        """会话闭合：热日志 + chronicle + 终局 unit 立即擢升（无 SessionMemoryBuffer 合并）。"""
        self._log.append(unit)
        self._route_chronicle(unit)
        self._promote_to_memory(unit)
        self._notify_after_ingest(unit)

    def ingest(self, unit: ExperienceUnit) -> None:
        self._log.append(unit)
        self._stamp_presence_bundle_on_unit(unit)

        partners = self._find_collision_partners(unit)
        if partners:
            self._do_collapse([unit] + partners)
            return

        self._finalize_single(unit)
        self._notify_after_ingest(unit)

    def tick(self) -> list[ExperienceUnit]:
        """补擢升热日志中遗漏单元（主路径已在 ingest 时即时 promote）。"""
        hot = self._log.recent()
        promoted: list[ExperienceUnit] = []
        for unit in hot:
            if unit.source == "collision":
                continue
            if unit.id not in self._memory_ingested_ids:
                self._promote_to_memory(unit)
                promoted.append(unit)
        self._log.purge_old()
        return promoted

    def _stamp_presence_bundle_on_unit(self, unit: ExperienceUnit) -> None:
        if unit.source in ("narrative", "surprise"):
            from agent.soul.life.anchor.presence_bundle import (
                presence_bundle_from_unit,
                stamp_presence_bundle,
            )

            stamp_presence_bundle(unit, presence_bundle_from_unit(unit))

    def _find_collision_partners(self, incoming: ExperienceUnit) -> list[ExperienceUnit]:
        if self._collapser is None:
            return []
        if incoming.source not in COLLISION_SOURCES:
            return []

        other_sources = COLLISION_SOURCES - {incoming.source}
        incoming_ts = _parse_ts(incoming.ts)

        partners: list[ExperienceUnit] = []
        seen_sources: set[str] = {incoming.source}

        candidates = self._log.recent()[-EXPERIENCE_COLLISION_SCAN_LIMIT:]
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
                salience_note="；".join(
                    part.strip()
                    for part in (
                        merged_text,
                        *(u.feeling.salience_note for u in units),
                    )
                    if part.strip()
                ),
            ),
            source="collision",
        )

        self._log.append(collision_unit)
        self._write_collision_chronicle(collision_unit, merged_text, has_user=has_user)
        self._promote_to_memory(collision_unit)

    def _notify_after_ingest(self, unit: ExperienceUnit) -> None:
        if self._after_ingest is not None:
            self._after_ingest(unit)

    def _finalize_single(self, unit: ExperienceUnit) -> None:
        self._route_chronicle(unit)
        self._promote_to_memory(unit)

    def _route_chronicle(self, unit: ExperienceUnit) -> None:
        if is_reality_source(unit.source):
            return
        if is_virtual_source(unit.source):
            self._write_virtual(unit)

    def _write_virtual(self, unit: ExperienceUnit) -> None:
        if self._virtual_chronicle is None:
            return
        from agent.soul.life.virtual.chronicle.adapter import virtual_entry_from_unit

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
            from agent.soul.life.anchor.chronicle.entry import AnchorChronicleEntry, AnchorChronicleKind

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
        from agent.soul.life.virtual.chronicle.adapter import collision_entry_from_unit

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
        promote_unit_to_memory(self._memory_port, unit)
        self._memory_ingested_ids.add(unit.id)

    def _retract_participants_from_memory(self, units: list[ExperienceUnit]) -> None:
        if self._memory_port is None:
            return
        for u in units:
            if self._memory_port.retract_experience(u.id):
                self._memory_ingested_ids.discard(u.id)


ExperienceOrchestrator = ExperienceUnitManager


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
