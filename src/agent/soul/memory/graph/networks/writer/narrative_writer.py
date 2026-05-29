from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.memory.emotion_intensity import infer_emotion_intensity
from agent.soul.memory.unit import MemoryTier, NarrativeMemory, Valence
from agent.soul.memory.graph.node_store import GraphNodeStore

if TYPE_CHECKING:
    from infra.llm import BaseLLM
    from agent.soul.memory.unit import MemoryUnit


_SYSTEM = """\
You are a memory narrative system. Weave factual/reconstructive fragments into one coherent first-person narrative memory.

Rules:
- focus: core theme, <=12 chars
- narrative: first-person paragraph, 100-300 chars
- emotion: named emotion string
- valence: "positive" | "negative" | "mixed" | "neutral"
- base_activation: 0.4~1.0

Output valid JSON only."""

_SCHEMA = """\
{
  "focus": "",
  "narrative": "",
  "emotion": "",
  "valence": "neutral",
  "base_activation": 0.7
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"no JSON in LLM output: {raw[:200]}")


def _valence(v: str) -> Valence:
    try:
        return Valence(v)
    except ValueError:
        return Valence.neutral


def _render_unit(unit: MemoryUnit) -> str:
    parts = [f"[{unit.MEMORY_TYPE}] {unit.focus}"]
    if hasattr(unit, "fact") and unit.fact:
        parts.append(f"fact: {unit.fact}")
    if hasattr(unit, "reconstructed_fact") and unit.reconstructed_fact:
        parts.append(f"reconstructed: {unit.reconstructed_fact}")
    if hasattr(unit, "narrative") and unit.narrative:
        parts.append(f"narrative: {unit.narrative}")
    if unit.emotion:
        parts.append(f"emotion: {unit.emotion} ({unit.emotion_intensity:.1f})")
    return "  ".join(parts)


class NarrativeWriter:
    def __init__(
        self,
        llm: BaseLLM,
        store: GraphNodeStore,
        on_written: Callable[[MemoryUnit], None] | None = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._on_written = on_written

    def write(
        self,
        source_unit_ids: list[str],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> NarrativeMemory | None:
        source_units = self._store.get_many(source_unit_ids)
        if not source_units:
            return None
        return self.write_from_units(
            source_units=source_units,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )

    def write_from_units(
        self,
        source_units: list[MemoryUnit],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> NarrativeMemory:
        unit = self._extract(source_units, chapter, persona_snapshot, emotional_context)
        self._store.put(unit)
        for src in source_units:
            self._store.add_narrative_ref(src.id)
        if self._on_written is not None:
            self._on_written(unit)
        return unit

    def _extract(
        self,
        source_units: list[MemoryUnit],
        chapter: str,
        persona_snapshot: str,
        emotional_context: str,
    ) -> NarrativeMemory:
        memories_text = "\n".join(
            f"{i + 1}. {_render_unit(u)}" for i, u in enumerate(source_units)
        )
        persona_section = (
            f"[persona]\n{persona_snapshot}\n\n" if persona_snapshot.strip() else ""
        )
        emotion_section = (
            f"[emotion]\n{emotional_context}\n\n" if emotional_context.strip() else ""
        )
        prompt = (
            f"{persona_section}"
            f"{emotion_section}"
            f"[chapter] {chapter}\n\n"
            f"[fragments x{len(source_units)}]\n{memories_text}\n\n"
            f"Output narrative JSON:\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse(raw, source_units=source_units, chapter=chapter)

    def _parse(
        self,
        raw: str,
        source_units: list[MemoryUnit],
        chapter: str,
    ) -> NarrativeMemory:
        d = _extract_json(raw)
        narrative = d.get("narrative", "")
        emotion = d.get("emotion", "")
        return NarrativeMemory(
            focus=d.get("focus", chapter or "untitled"),
            narrative=narrative,
            source_ids=[u.id for u in source_units],
            chapter=chapter,
            emotion=emotion,
            emotion_intensity=infer_emotion_intensity(emotion, narrative),
            valence=_valence(d.get("valence", "neutral")),
            base_activation=float(d.get("base_activation", 0.7)),
            tier=MemoryTier.long,
        )
