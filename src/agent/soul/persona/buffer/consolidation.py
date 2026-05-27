from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from infra.llm import BaseLLM
from agent.soul.memory.unit import MemoryUnit
from agent.soul.persona.profile.profile import PersonaProfile

from .clustering import DriftClusterConfig, DriftUnitCluster, EmbedderBackend, cluster_memory_units
from .drift_writer import ClusterDraft, DriftDistillWriter, MonthDraft
from ..self_concept.concept import SelfConcept, SelfConceptDelta

if TYPE_CHECKING:
    from .buffer import ExperienceBuffer
    from .store import BufferMeta


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_month(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


@dataclass(frozen=True)
class DriftWritePlan:
    delta: SelfConceptDelta
    signal_ids: list[str]
    cluster_count: int = 0
    unit_count: int = 0
    cluster_themes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MonthlyDriftResult:
    ok: bool
    applied: bool
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    plan: DriftWritePlan | None = None


class MemoryDriftUnitPort(Protocol):
    """Memory 侧：提供漂移所需的 raw memory units（不含蒸馏）。"""

    def list_drift_units(
        self,
        *,
        month: str,
        anchor_unit_ids: list[str] | None = None,
        limit: int = 120,
    ) -> list[MemoryUnit]:
        ...

class MonthlyDriftUpdater:
    """唯一 self_concept 漂移编排 skill。

    raw units → embedding 聚类 → 分簇蒸馏 → 向上合并 → 对照画像修订 → apply_delta
    """

    _DEFAULT_UNIT_LIMIT = 120

    def __init__(self, *, cluster_cfg: DriftClusterConfig | None = None) -> None:
        self._cluster_cfg = cluster_cfg or DriftClusterConfig()

    def is_due(
        self,
        meta: BufferMeta,
        *,
        month: str | None = None,
        force: bool = False,
    ) -> bool:
        if force:
            return True
        target = month or current_month()
        return meta.last_drift_month != target

    def run(
        self,
        *,
        buffer: ExperienceBuffer,
        meta: BufferMeta,
        concept: SelfConcept,
        profile: PersonaProfile,
        memory_port: MemoryDriftUnitPort | None = None,
        embedder: EmbedderBackend | None = None,
        llm: BaseLLM | None = None,
        month: str | None = None,
        force: bool = False,
    ) -> MonthlyDriftResult:
        from ..self_concept.concept import SelfConceptDelta

        target_month = month or current_month()
        if not self.is_due(meta, month=target_month, force=force):
            return MonthlyDriftResult(
                ok=True,
                applied=False,
                reason="not_due",
                detail={"month": target_month},
            )

        pending = buffer.pending_for_month(target_month)
        if not pending:
            return MonthlyDriftResult(
                ok=True,
                applied=False,
                reason="no_pending_signals",
                detail={"month": target_month},
            )

        signal_ids = [s.id for s in pending]
        themes = [s.theme for s in pending if s.theme.strip()]
        anchor_ids: list[str] = []
        for signal in pending:
            anchor_ids.extend(signal.unit_ids)
        anchor_ids = list(dict.fromkeys(uid for uid in anchor_ids if uid))

        if memory_port is None:
            return MonthlyDriftResult(
                ok=True,
                applied=False,
                reason="no_memory_port",
                detail={
                    "month": target_month,
                    "pending_count": len(pending),
                    "themes": themes,
                },
            )

        units = memory_port.list_drift_units(
            month=target_month,
            anchor_unit_ids=anchor_ids or None,
            limit=self._DEFAULT_UNIT_LIMIT,
        )
        if not units:
            return MonthlyDriftResult(
                ok=True,
                applied=False,
                reason="no_drift_units",
                detail={
                    "month": target_month,
                    "pending_count": len(pending),
                    "themes": themes,
                    "anchor_count": len(anchor_ids),
                },
            )

        clusters = cluster_memory_units(units, embedder, cfg=self._cluster_cfg)
        if not clusters:
            return MonthlyDriftResult(
                ok=True,
                applied=False,
                reason="no_clusters",
                detail={
                    "month": target_month,
                    "unit_count": len(units),
                },
            )

        if llm is None:
            return MonthlyDriftResult(
                ok=True,
                applied=False,
                reason="no_llm",
                detail={
                    "month": target_month,
                    "unit_count": len(units),
                    "cluster_count": len(clusters),
                    "cluster_themes": [c.theme for c in clusters],
                },
            )

        writer = DriftDistillWriter(llm, cfg=self._cluster_cfg)
        cluster_drafts: list[ClusterDraft] = []
        for cluster in clusters:
            cluster_drafts.append(writer.distill_cluster(cluster, profile, concept))

        month_draft = writer.reduce_drafts(cluster_drafts, month=target_month)
        delta = writer.revise_against_portrait(profile, concept, month_draft)
        if delta.is_empty():
            return MonthlyDriftResult(
                ok=True,
                applied=False,
                reason="empty_delta",
                detail={
                    "month": target_month,
                    "unit_count": len(units),
                    "cluster_count": len(clusters),
                    "cluster_themes": [c.theme for c in clusters],
                    "month_insight": month_draft.insight,
                },
            )

        plan = DriftWritePlan(
            delta=delta,
            signal_ids=signal_ids,
            cluster_count=len(clusters),
            unit_count=len(units),
            cluster_themes=[c.theme for c in clusters],
        )
        return MonthlyDriftResult(
            ok=True,
            applied=True,
            reason="self_concept_drifted",
            plan=plan,
            detail={
                "month": target_month,
                "pending_count": len(pending),
                "themes": themes,
                "unit_count": len(units),
                "cluster_count": len(clusters),
                "cluster_themes": plan.cluster_themes,
                "month_insight": month_draft.insight,
            },
        )
