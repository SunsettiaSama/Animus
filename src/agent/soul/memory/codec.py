from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent.soul.memory.unit import (
    FactualMemory,
    MemoryTier,
    MemoryUnit,
    NarrativeMemory,
    ReconstructiveMemory,
    Valence,
)

_TYPE_MAP: dict[str, type[MemoryUnit]] = {
    "factual":         FactualMemory,
    "reconstructive":  ReconstructiveMemory,
    "narrative":       NarrativeMemory,
}


def _dt_to_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def unit_to_dict(unit: MemoryUnit) -> dict[str, Any]:
    """MemoryUnit → 可 JSON 序列化的字典（datetime → ISO, enum → str）。"""
    d: dict[str, Any] = {
        "memory_type":        unit.MEMORY_TYPE,
        "id":                 unit.id,
        "focus":              unit.focus,
        "emotion":            unit.emotion,
        "emotion_intensity":  unit.emotion_intensity,
        "valence":            unit.valence.value,
        "tier":               unit.tier.value,
        "base_activation":    unit.base_activation,
        "recall_count":        unit.recall_count,
        "rehearsal_count":     unit.rehearsal_count,
        "narrative_ref_count": unit.narrative_ref_count,
        "last_accessed":       _dt_to_str(unit.last_accessed),
        "created_at":         _dt_to_str(unit.created_at),
        "meta":               unit.meta,
    }
    if isinstance(unit, FactualMemory):
        d["fact"]       = unit.fact
        d["perception"] = unit.perception
    elif isinstance(unit, ReconstructiveMemory):
        d["source_id"]          = unit.source_id
        d["reconstructed_fact"] = unit.reconstructed_fact
        d["trigger"]            = unit.trigger
    elif isinstance(unit, NarrativeMemory):
        d["narrative"]   = unit.narrative
        d["source_ids"]  = unit.source_ids
        d["chapter"]     = unit.chapter
    return d


def unit_to_json(unit: MemoryUnit) -> str:
    return json.dumps(unit_to_dict(unit), ensure_ascii=False)


def unit_from_dict(d: dict[str, Any]) -> MemoryUnit:
    """字典 → MemoryUnit（自动按 memory_type 还原正确子类）。"""
    memory_type = d["memory_type"]
    cls = _TYPE_MAP.get(memory_type)
    if cls is None:
        raise ValueError(f"Unknown memory_type: {memory_type!r}")

    common: dict[str, Any] = {
        "id":                d["id"],
        "focus":             d["focus"],
        "emotion":           d.get("emotion", ""),
        "emotion_intensity": float(d.get("emotion_intensity", 0.0)),
        "valence":           Valence(d.get("valence", "neutral")),
        "tier":              MemoryTier(d.get("tier", "short_term")),
        "base_activation":   float(d.get("base_activation", 0.5)),
        "recall_count":        int(d.get("recall_count", 0)),
        "rehearsal_count":     int(d.get("rehearsal_count", 0)),
        "narrative_ref_count": int(d.get("narrative_ref_count", 0)),
        "last_accessed":       _str_to_dt(d["last_accessed"]),
        "created_at":        _str_to_dt(d["created_at"]),
        "meta":              d.get("meta") or {},
    }

    if cls is FactualMemory:
        return FactualMemory(
            **common,
            fact       = d.get("fact", ""),
            perception = d.get("perception", ""),
        )
    if cls is ReconstructiveMemory:
        return ReconstructiveMemory(
            **common,
            source_id          = d.get("source_id", ""),
            reconstructed_fact = d.get("reconstructed_fact", ""),
            trigger            = d.get("trigger", ""),
        )
    if cls is NarrativeMemory:
        return NarrativeMemory(
            **common,
            narrative  = d.get("narrative", ""),
            source_ids = d.get("source_ids") or [],
            chapter    = d.get("chapter", ""),
        )
    raise ValueError(f"Unhandled class: {cls}")


def unit_from_json(s: str) -> MemoryUnit:
    return unit_from_dict(json.loads(s))


def scored_to_dict(scored) -> dict[str, Any]:
    """ScoredUnit → 可 JSON 序列化的检索结果。"""
    d = unit_to_dict(scored.unit)
    d["relevance"] = scored.relevance
    d["activation"] = scored.activation
    d["final_score"] = scored.final_score
    d["source"] = scored.source
    return d
