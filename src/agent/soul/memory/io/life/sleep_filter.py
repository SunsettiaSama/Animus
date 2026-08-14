from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent.soul.life.experience.domain.anchor_codec import read_anchor_context
from agent.soul.life.experience.domain.unit import ExperienceActionKind, ExperienceUnit
from agent.soul.memory.io.life.request import ExperienceIngestInbound

_ANCHORED_SOURCES = frozenset({"user", "interaction", "collision", "task", "narrative"})
_STRICT_SOURCES = frozenset({"heartbeat", "system"})
_HALLUCINATION_MARKERS = (
    "也许",
    "或许",
    "可能是",
    "好像",
    "仿佛",
    "想象",
    "幻想",
    "猜测",
    "推测",
    "感觉好像",
    "不确定",
    "我猜",
    "大概是",
    "或许发生了",
)
_EXTERNAL_EVIDENCE_KEYS = frozenset(
    {
        "landmark_episode",
        "tool_result",
        "tool_name",
        "user_text",
        "agent_text",
        "interaction_id",
        "task_id",
        "collision",
    }
)


class SleepFilterDecision(str, Enum):
    pass_ = "pass"
    reject = "reject"


@dataclass(frozen=True)
class SleepFilterResult:
    decision: SleepFilterDecision
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision is SleepFilterDecision.pass_


@dataclass(frozen=True)
class SleepFilterConfig:
    enabled: bool = True
    min_salience: float = 0.0
    reject_unanchored_internal_thought: bool = True


class SleepFilterChannel:
    """Memory 写入前的 sleep 幻觉筛选通道（不改动 SleepService 巩固流程）。"""

    def __init__(self, cfg: SleepFilterConfig | None = None) -> None:
        self._cfg = cfg or SleepFilterConfig()

    def screen(self, inbound: ExperienceIngestInbound) -> SleepFilterResult:
        if not self._cfg.enabled:
            return SleepFilterResult(
                decision=SleepFilterDecision.pass_,
                reason="sleep_filter_disabled",
            )
        unit = inbound.unit
        if unit.feeling.salience < self._cfg.min_salience:
            return SleepFilterResult(
                decision=SleepFilterDecision.reject,
                reason="salience_below_threshold",
            )
        if self._has_strong_anchor(unit):
            return SleepFilterResult(
                decision=SleepFilterDecision.pass_,
                reason="anchored_evidence",
            )
        if self._is_unanchored_internal_hallucination(unit):
            return SleepFilterResult(
                decision=SleepFilterDecision.reject,
                reason="unanchored_internal_hallucination",
            )
        if unit.source in _STRICT_SOURCES and not self._has_external_signal(unit):
            return SleepFilterResult(
                decision=SleepFilterDecision.reject,
                reason="strict_source_without_external_signal",
            )
        if not self._has_external_signal(unit):
            return SleepFilterResult(
                decision=SleepFilterDecision.reject,
                reason="no_external_signal",
            )
        return SleepFilterResult(
            decision=SleepFilterDecision.pass_,
            reason="external_signal",
        )

    def _has_strong_anchor(self, unit: ExperienceUnit) -> bool:
        if dict(unit.evidence.get("landmark_episode") or {}):
            return True
        ctx = read_anchor_context(unit)
        if ctx is not None and (
            ctx.interactor_id.strip()
            or ctx.session_id.strip()
            or ctx.interaction_id.strip()
        ):
            return True
        if unit.source in _ANCHORED_SOURCES and self._has_external_signal(unit):
            return True
        for key in _EXTERNAL_EVIDENCE_KEYS:
            value = unit.evidence.get(key)
            if value:
                return True
        return False

    def _has_external_signal(self, unit: ExperienceUnit) -> bool:
        if unit.situation.perception.strip():
            return True
        if unit.situation.session_id.strip():
            return True
        if unit.action.kind in (
            ExperienceActionKind.speaking,
            ExperienceActionKind.tool_use,
            ExperienceActionKind.attending,
        ) and unit.action.content.strip():
            return True
        if unit.source in _ANCHORED_SOURCES and (
            unit.situation.narration.strip() or unit.action.content.strip()
        ):
            return True
        for key in _EXTERNAL_EVIDENCE_KEYS:
            if unit.evidence.get(key):
                return True
        return False

    def _is_unanchored_internal_hallucination(self, unit: ExperienceUnit) -> bool:
        if not self._cfg.reject_unanchored_internal_thought:
            return False
        if self._has_strong_anchor(unit):
            return False
        if unit.action.kind not in (
            ExperienceActionKind.reasoning,
            ExperienceActionKind.remembering,
            ExperienceActionKind.deciding,
        ):
            if unit.source not in _STRICT_SOURCES:
                return False
        text = "\n".join(
            part
            for part in (
                unit.situation.narration,
                unit.situation.prior_thought,
                unit.situation.perception,
                unit.action.content,
                unit.feeling.salience_note,
                unit.feeling.subjective_narrative,
            )
            if part and part.strip()
        )
        if not text.strip():
            return True
        lowered = text.lower()
        if any(marker in text or marker in lowered for marker in _HALLUCINATION_MARKERS):
            return True
        if unit.source in _STRICT_SOURCES and not unit.situation.perception.strip():
            return True
        if unit.action.kind in (
            ExperienceActionKind.reasoning,
            ExperienceActionKind.remembering,
            ExperienceActionKind.deciding,
        ) and not unit.situation.perception.strip() and not unit.evidence:
            return True
        return False
