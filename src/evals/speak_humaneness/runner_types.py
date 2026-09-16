from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 拟人度综合 = 画像匹配 + 图灵盲测 + 行为统计，缺项时在剩余维度上重归一。
HUMANNESS_WEIGHTS: dict[str, float] = {
    "portrait": 0.40,
    "turing": 0.35,
    "behavior": 0.25,
}


@dataclass
class CaseRecord:
    """单条 case × 单条管线的完整评测记录。"""

    case_id: str
    responder: str
    tags: tuple[str, ...]
    ok: bool
    transcript: dict[str, Any]
    behavior: dict[str, Any]
    scores: dict[str, Any] = field(default_factory=dict)
    known_user: dict[str, Any] | None = None
    blind_both: dict[str, Any] | None = None
    extraction: dict[str, Any] | None = None
    match: dict[str, Any] | None = None
    error: str = ""
    wall_ms_total: float = 0.0
    async_fallback_used: int = 0
    created_at: str = ""
    arm_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "responder": self.responder,
            "tags": list(self.tags),
            "ok": self.ok,
            "transcript": self.transcript,
            "behavior": self.behavior,
            "scores": self.scores,
            "known_user": self.known_user,
            "blind_both": self.blind_both,
            "extraction": self.extraction,
            "match": self.match,
            "error": self.error,
            "wall_ms_total": self.wall_ms_total,
            "async_fallback_used": self.async_fallback_used,
            "created_at": self.created_at,
            "arm_events": list(self.arm_events),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CaseRecord":
        return cls(
            case_id=str(raw["case_id"]),
            responder=str(raw["responder"]),
            tags=tuple(str(item) for item in raw.get("tags", [])),
            ok=bool(raw.get("ok", False)),
            transcript=dict(raw.get("transcript", {})),
            behavior=dict(raw.get("behavior", {})),
            scores=dict(raw.get("scores", {})),
            known_user=raw.get("known_user"),
            blind_both=raw.get("blind_both"),
            extraction=raw.get("extraction"),
            match=raw.get("match"),
            error=str(raw.get("error", "")),
            wall_ms_total=float(raw.get("wall_ms_total", 0.0)),
            async_fallback_used=int(raw.get("async_fallback_used", 0)),
            created_at=str(raw.get("created_at", "")),
            arm_events=list(raw.get("arm_events", [])),
        )


def humanness_score(
    *,
    portrait_fidelity: float | None,
    blind_human: float | None,
    behavior_naturalness: float | None,
    weights: dict[str, float] | None = None,
) -> float | None:
    active = HUMANNESS_WEIGHTS if weights is None else weights
    parts: list[tuple[float, float]] = []
    if portrait_fidelity is not None:
        parts.append((active["portrait"], portrait_fidelity))
    if blind_human is not None:
        parts.append((active["turing"], blind_human))
    if behavior_naturalness is not None:
        parts.append((active["behavior"], behavior_naturalness))
    if not parts:
        return None
    total_weight = sum(weight for weight, _ in parts)
    value = sum(weight * item for weight, item in parts) / total_weight
    return round(max(0.0, min(1.0, value)), 4)
