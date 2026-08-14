"""Gather / fingerprint mid-long-term memory for memory_distill."""

import hashlib
from typing import Any, Protocol

from worker.state.memory_distill.bundle import PortraitSourceBundle

_MAX_RECENT = 40
_MAX_HYBRID = 12
_MAX_LINES = 48
_MAX_LINE_CHARS = 220
_MAX_MEDIUM_CHARS = 1800


class MemoryPort(Protocol):
    def search(self, mode: str, **kwargs: Any) -> list[dict]: ...


class MediumPort(Protocol):
    def render(self) -> str: ...


def _clamp_chars(text: str, max_chars: int) -> str:
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _item_id(item: dict[str, Any]) -> str:
    for key in ("id", "unit_id", "node_id"):
        val = str(item.get(key, "")).strip()
        if val:
            return val
    unit = item.get("unit") or item.get("node") or {}
    if isinstance(unit, dict):
        for key in ("id", "unit_id", "node_id"):
            val = str(unit.get(key, "")).strip()
            if val:
                return val
    return ""


def _item_line(item: dict[str, Any]) -> str:
    for key in ("render_line", "line", "text", "content", "summary"):
        val = str(item.get(key, "")).strip()
        if val:
            return _clamp_chars(val, _MAX_LINE_CHARS)

    bodies = (
        item,
        item.get("unit") if isinstance(item.get("unit"), dict) else {},
        item.get("node") if isinstance(item.get("node"), dict) else {},
    )
    for body in bodies:
        if not isinstance(body, dict) or not body:
            continue
        for key in ("fact", "narrative", "reconstructed_fact", "perception", "content"):
            val = str(body.get(key, "")).strip()
            if val:
                focus = str(body.get("focus", "") or item.get("focus", "")).strip()
                prefix = f"[{focus}] " if focus else ""
                return _clamp_chars(prefix + val, _MAX_LINE_CHARS)
    return ""


def gather_portrait_source(
    *,
    memory: MemoryPort | None,
    medium: MediumPort | None = None,
    persona_revision: str = "",
    stable_anchor: str = "",
    hybrid_query: str = "",
    worker_unit_lines: list[str] | tuple[str, ...] | None = None,
    recent_limit: int = _MAX_RECENT,
    hybrid_top_k: int = _MAX_HYBRID,
) -> PortraitSourceBundle:
    """Collect, dedupe, truncate mid/long-term memory materials."""
    lines: list[str] = []
    unit_ids: list[str] = []
    seen_ids: set[str] = set()
    seen_lines: set[str] = set()

    def _ingest(items: list[dict[str, Any]]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            line = _item_line(item)
            if not line:
                continue
            uid = _item_id(item)
            if uid and uid in seen_ids:
                continue
            if line in seen_lines:
                continue
            if uid:
                seen_ids.add(uid)
                unit_ids.append(uid)
            seen_lines.add(line)
            lines.append(line)
            if len(lines) >= _MAX_LINES:
                return

    if memory is not None:
        _ingest(memory.search("recent", limit=recent_limit))
        q = hybrid_query.strip()
        if q and len(lines) < _MAX_LINES:
            _ingest(memory.search("hybrid", query=q, top_k=hybrid_top_k))

    medium_text = ""
    if medium is not None:
        medium_text = _clamp_chars(medium.render(), _MAX_MEDIUM_CHARS)

    work_lines = tuple(
        _clamp_chars(str(line), _MAX_LINE_CHARS)
        for line in (worker_unit_lines or ())
        if str(line).strip()
    )[:_MAX_LINES]

    ids_key = ",".join(unit_ids)
    med_key = _hash_text(medium_text) if medium_text else "0"
    work_key = _hash_text("\n".join(work_lines)) if work_lines else "0"
    persona_key = persona_revision.strip() or "raw"
    source_revision = (
        f"{persona_key}|ltm:{_hash_text(ids_key)}|med:{med_key}"
        f"|work:{work_key}|n:{len(lines)}"
    )

    return PortraitSourceBundle(
        lines=tuple(lines),
        unit_ids=tuple(unit_ids),
        medium_text=medium_text,
        persona_revision=persona_revision.strip(),
        stable_anchor=stable_anchor.strip(),
        source_revision=source_revision,
        worker_unit_lines=work_lines,
    )
