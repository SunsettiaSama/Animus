"""Dependency resolvers for the memory_distill fallback chain."""

from pathlib import Path
from typing import Any


def resolve_memory_port(soul: Any) -> Any | None:
    if soul is None:
        return None
    memory = getattr(soul, "memory", None)
    if memory is None:
        return None
    api = getattr(memory, "api", None)
    return api if api is not None else memory


def resolve_persona_revision(soul: Any) -> str:
    if soul is None:
        return ""
    persona = getattr(soul, "persona", None)
    if persona is None:
        return ""
    svc = getattr(persona, "service", persona)
    if hasattr(svc, "portrait_revision"):
        return str(svc.portrait_revision() or "")
    return ""


def resolve_stable_anchor(soul: Any) -> str:
    if soul is None:
        return ""
    if hasattr(soul, "get_persona_snapshot"):
        snap = soul.get_persona_snapshot(session_id="tao")
    elif hasattr(soul, "query_persona"):
        snap = soul.query_persona(session_id="tao")
    else:
        return ""
    if not isinstance(snap, dict):
        return ""
    distill = snap.get("persona_distill") or {}
    slices = distill.get("slices") if isinstance(distill, dict) else None
    if isinstance(slices, dict):
        anchor = str(slices.get("memory_anchor", "")).strip()
        if anchor:
            return anchor
    from agent.soul.memory.facade.persona_context import build_agent_persona_narrative

    return build_agent_persona_narrative(snap)


def resolve_hybrid_query(soul: Any) -> str:
    if soul is None:
        return ""
    persona = getattr(soul, "persona", None)
    if persona is None:
        return ""
    svc = getattr(persona, "service", persona)
    if hasattr(svc, "bias_query"):
        return str(svc.bias_query("") or "").strip()
    return ""


def build_medium_reader(memory_dir: str | Path | None = None) -> Any | None:
    """Load Worker React mid-term memory for portrait source (read-only)."""
    if not memory_dir:
        return None
    path = Path(memory_dir)
    if not path.is_dir():
        return None
    from config.agent.memory.medium_term_config import MediumTermMemoryConfig
    from worker.context.medium_term.memory import RecentHistoryMemory

    cfg = MediumTermMemoryConfig(
        enabled=True,
        memory_dir=str(path),
        distill_on_write=False,
        consolidate_enabled=False,
    )
    return RecentHistoryMemory(cfg, llm=None)
