from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent.soul.memory.domain import (
    EdgeType,
    FactualMemory,
    GraphNode,
    MemoryEdge,
    MemoryNetwork,
    MemoryTier,
    NarrativeMemory,
    ReconstructiveMemory,
    SocialCoreNode,
    SocialNeighborhoodNode,
    SocialNodeRole,
    Valence,
)

_TYPE_MAP: dict[str, type[GraphNode]] = {
    "factual": FactualMemory,
    "reconstructive": ReconstructiveMemory,
    "narrative": NarrativeMemory,
    "social_core": SocialCoreNode,
    "social_neighborhood": SocialNeighborhoodNode,
}


def _dt_to_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _str_to_dt(s: str | datetime) -> datetime:
    if isinstance(s, datetime):
        dt = s
    else:
        dt = datetime.fromisoformat(str(s))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def node_to_dict(node: GraphNode) -> dict[str, Any]:
    d: dict[str, Any] = {
        "memory_type": node.NODE_KIND,
        "id": node.id,
        "network": node.network.value,
        "interactor_id": node.interactor_id,
        "focus": node.focus,
        "emotion": node.emotion,
        "emotion_intensity": node.emotion_intensity,
        "valence": node.valence.value,
        "tier": node.tier.value,
        "base_activation": node.base_activation,
        "recall_count": node.recall_count,
        "rehearsal_count": node.rehearsal_count,
        "narrative_ref_count": node.narrative_ref_count,
        "last_accessed": node.last_accessed.isoformat(),
        "created_at": node.created_at.isoformat(),
        "meta": dict(node.meta or {}),
    }
    if isinstance(node, FactualMemory):
        d["fact"] = node.fact
        d["perception"] = node.perception
        if node.life_event_id:
            d["meta"]["life_event_id"] = node.life_event_id
    elif isinstance(node, ReconstructiveMemory):
        d["source_id"] = node.source_id
        d["reconstructed_fact"] = node.reconstructed_fact
        d["trigger"] = node.trigger
    elif isinstance(node, NarrativeMemory):
        d["narrative"] = node.narrative
        d["source_ids"] = list(node.source_ids)
        d["chapter"] = node.chapter
    elif isinstance(node, SocialCoreNode):
        d["node_role"] = SocialNodeRole.core.value
        d["core_traits"] = node.core_traits
        d["trait_version"] = node.trait_version
        d["last_evolved_at"] = node.last_evolved_at.isoformat()
    elif isinstance(node, SocialNeighborhoodNode):
        d["node_role"] = SocialNodeRole.neighborhood.value
        d["neighborhood_label"] = node.label
        d["neighborhood_content"] = node.content
    return d


def node_to_row_params(node: GraphNode) -> dict[str, Any]:
    d = node_to_dict(node)
    role = d.get("node_role", "")
    if isinstance(node, SocialCoreNode):
        role = SocialNodeRole.core.value
    elif isinstance(node, SocialNeighborhoodNode):
        role = SocialNodeRole.neighborhood.value
    return {
        "id": d["id"],
        "memory_type": d["memory_type"],
        "network": d["network"],
        "interactor_id": d.get("interactor_id") or "",
        "node_role": role,
        "focus": d["focus"],
        "emotion": d["emotion"],
        "emotion_intensity": d["emotion_intensity"],
        "valence": d["valence"],
        "tier": d["tier"],
        "base_activation": d["base_activation"],
        "recall_count": d["recall_count"],
        "rehearsal_count": d["rehearsal_count"],
        "narrative_ref_count": d["narrative_ref_count"],
        "last_accessed": _dt_to_str(node.last_accessed),
        "created_at": _dt_to_str(node.created_at),
        "meta_json": json.dumps(d.get("meta") or {}, ensure_ascii=False),
        "fact": d.get("fact"),
        "perception": d.get("perception"),
        "source_id": d.get("source_id"),
        "reconstructed_fact": d.get("reconstructed_fact"),
        "trigger_ctx": d.get("trigger"),
        "narrative": d.get("narrative"),
        "source_ids_json": json.dumps(d.get("source_ids") or [], ensure_ascii=False),
        "chapter": d.get("chapter", ""),
        "core_traits": d.get("core_traits"),
        "trait_version": int(d.get("trait_version") or 1),
        "last_evolved_at": _dt_to_str(node.last_evolved_at) if isinstance(node, SocialCoreNode) else None,
        "neighborhood_label": d.get("neighborhood_label", ""),
        "neighborhood_content": d.get("neighborhood_content"),
    }


def row_to_node(row: dict) -> GraphNode:
    memory_type = row["memory_type"]
    cls = _TYPE_MAP.get(memory_type)
    if cls is None:
        raise ValueError(f"Unknown memory_type: {memory_type!r}")

    meta = json.loads(row["meta_json"]) if row.get("meta_json") else {}
    common: dict[str, Any] = {
        "id": row["id"],
        "focus": row["focus"],
        "emotion": row.get("emotion") or "",
        "emotion_intensity": float(row.get("emotion_intensity") or 0.0),
        "valence": Valence(row.get("valence") or "neutral"),
        "tier": MemoryTier(row.get("tier") or "short_term"),
        "base_activation": float(row.get("base_activation") or 0.5),
        "recall_count": int(row.get("recall_count") or 0),
        "rehearsal_count": int(row.get("rehearsal_count") or 0),
        "narrative_ref_count": int(row.get("narrative_ref_count") or 0),
        "last_accessed": _str_to_dt(row["last_accessed"]),
        "created_at": _str_to_dt(row["created_at"]),
        "meta": meta,
        "network": MemoryNetwork(row.get("network") or "event"),
        "interactor_id": row.get("interactor_id") or "",
    }

    if cls is FactualMemory:
        life_event_id = meta.get("life_event_id") or ""
        return FactualMemory(
            **common,
            fact=row.get("fact") or "",
            perception=row.get("perception") or "",
            life_event_id=str(life_event_id),
        )
    if cls is ReconstructiveMemory:
        return ReconstructiveMemory(
            **common,
            source_id=row.get("source_id") or "",
            reconstructed_fact=row.get("reconstructed_fact") or "",
            trigger=row.get("trigger_ctx") or "",
        )
    if cls is NarrativeMemory:
        source_ids = json.loads(row["source_ids_json"]) if row.get("source_ids_json") else []
        return NarrativeMemory(
            **common,
            narrative=row.get("narrative") or "",
            source_ids=source_ids,
            chapter=row.get("chapter") or "",
        )
    if cls is SocialCoreNode:
        evolved = row.get("last_evolved_at")
        return SocialCoreNode(
            **common,
            core_traits=row.get("core_traits") or "",
            trait_version=int(row.get("trait_version") or 1),
            last_evolved_at=_str_to_dt(evolved) if evolved else common["created_at"],
        )
    if cls is SocialNeighborhoodNode:
        return SocialNeighborhoodNode(
            **common,
            label=row.get("neighborhood_label") or "",
            content=row.get("neighborhood_content") or "",
        )
    raise ValueError(f"Unhandled node class: {cls}")


def edge_to_row_params(edge: MemoryEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "from_id": edge.from_id,
        "to_id": edge.to_id,
        "edge_type": edge.edge_type.value,
        "weight": edge.weight,
        "meta_json": json.dumps(edge.meta or {}, ensure_ascii=False),
        "created_at": _dt_to_str(datetime.now(timezone.utc)),
    }


def row_to_edge(row: dict) -> MemoryEdge:
    return MemoryEdge(
        id=row["id"],
        from_id=row["from_id"],
        to_id=row["to_id"],
        edge_type=EdgeType(row["edge_type"]),
        weight=float(row.get("weight") or 1.0),
        meta=json.loads(row["meta_json"]) if row.get("meta_json") else {},
    )


def unit_from_dict(d: dict[str, Any]) -> GraphNode:
    row: dict[str, Any] = {
        "memory_type": d["memory_type"],
        "id": d["id"],
        "focus": d["focus"],
        "emotion": d.get("emotion", ""),
        "emotion_intensity": d.get("emotion_intensity", 0.0),
        "valence": d.get("valence", "neutral"),
        "tier": d.get("tier", "short_term"),
        "base_activation": d.get("base_activation", 0.5),
        "recall_count": d.get("recall_count", 0),
        "rehearsal_count": d.get("rehearsal_count", 0),
        "narrative_ref_count": d.get("narrative_ref_count", 0),
        "last_accessed": d["last_accessed"],
        "created_at": d["created_at"],
        "meta_json": json.dumps(d.get("meta") or {}),
        "network": d.get("network", "event"),
        "interactor_id": d.get("interactor_id", ""),
        "fact": d.get("fact"),
        "perception": d.get("perception"),
        "source_id": d.get("source_id"),
        "reconstructed_fact": d.get("reconstructed_fact"),
        "trigger_ctx": d.get("trigger"),
        "narrative": d.get("narrative"),
        "source_ids_json": json.dumps(d.get("source_ids") or []),
        "chapter": d.get("chapter", ""),
        "core_traits": d.get("core_traits"),
        "trait_version": d.get("trait_version", 1),
        "neighborhood_label": d.get("neighborhood_label", ""),
        "neighborhood_content": d.get("neighborhood_content"),
    }
    if d.get("life_event_id"):
        meta = json.loads(row["meta_json"])
        meta["life_event_id"] = d["life_event_id"]
        row["meta_json"] = json.dumps(meta, ensure_ascii=False)
    return row_to_node(row)


unit_to_dict = node_to_dict


def unit_to_json(node: GraphNode) -> str:
    return json.dumps(node_to_dict(node), ensure_ascii=False)


def unit_from_json(s: str) -> GraphNode:
    return unit_from_dict(json.loads(s))


def scored_to_dict(scored) -> dict[str, Any]:
    d = node_to_dict(scored.unit)
    d["relevance"] = scored.relevance
    d["activation"] = scored.activation
    d["final_score"] = scored.final_score
    d["source"] = scored.source
    return d
