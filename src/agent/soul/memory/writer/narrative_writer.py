from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.memory.unit import MemoryTier, NarrativeMemory, Valence

if TYPE_CHECKING:
    from infra.llm import BaseLLM
    from agent.soul.memory.long_term.manager import LongTermMemoryManager
    from agent.soul.memory.unit import MemoryUnit


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """\
你是记忆叙事系统。将若干事实性/重构型记忆片段编织为一段连贯的叙事记忆，\
模拟人类将零散记忆整合为"人生故事"的过程。

规则：
- focus: 整段叙事的核心主题，12字以内
- narrative: 第一人称叙事段落，100~300字；自然流畅，允许情感色彩；
  不要逐条列举原始记忆，而是提炼成有温度的故事
- emotion: 这段叙事折射的主要情绪，命名字符串（如"成就感"、"怀念"、"不安"）
- emotion_intensity: 情绪烈度，浮点数 0.0~1.0
- valence: 严格输出 "positive" | "negative" | "mixed" | "neutral" 之一
- base_activation: 叙事记忆的初始重要性，浮点数 0.4~1.0

严格输出合法 JSON，不含任何其他文字。"""

_SCHEMA = """\
{
  "focus": "",
  "narrative": "",
  "emotion": "",
  "emotion_intensity": 0.0,
  "valence": "neutral",
  "base_activation": 0.7
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"LLM 输出中未找到合法 JSON：{raw[:200]}")


def _valence(v: str) -> Valence:
    try:
        return Valence(v)
    except ValueError:
        return Valence.neutral


def _render_unit(unit: MemoryUnit) -> str:
    """将单条 MemoryUnit 渲染为 prompt 可读的文本行。"""
    parts = [f"[{unit.MEMORY_TYPE}] {unit.focus}"]
    if hasattr(unit, "fact") and unit.fact:
        parts.append(f"事实：{unit.fact}")
    if hasattr(unit, "reconstructed_fact") and unit.reconstructed_fact:
        parts.append(f"重构：{unit.reconstructed_fact}")
    if hasattr(unit, "narrative") and unit.narrative:
        parts.append(f"叙事：{unit.narrative}")
    if unit.emotion:
        parts.append(f"情绪：{unit.emotion}（烈度 {unit.emotion_intensity:.1f}）")
    return "  ".join(parts)


class NarrativeWriter:
    """叙事性记忆生成写入器。

    将若干事实性/重构型记忆单元整合为一条 `NarrativeMemory`，写入长期记忆。
    由 `LifeManager` 在日终回顾（daily review）或章节归档时调用。

    两种调用方式
    --------
    1. **write(source_unit_ids, chapter, ...)** — 传入 id 列表，内部从 LTM 拉取完整 unit
    2. **write_from_units(source_units, chapter, ...)** — 传入已在内存中的 unit 列表
       （适合 LifeManager 已经持有 unit 对象时，避免二次读 DB）

    参数说明
    --------
    llm
        底层推理实例
    ltm
        长期记忆管理器（MySQL）；用于读取 source units 和写入 NarrativeMemory
    """

    def __init__(
        self,
        llm: BaseLLM,
        store: LongTermMemoryManager,
        on_written: Callable[[MemoryUnit], None] | None = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._on_written = on_written

    # ── Public API ────────────────────────────────────────────────────────────

    def write(
        self,
        source_unit_ids: list[str],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> NarrativeMemory | None:
        """从 LTM 拉取 source units，合成叙事并写入。

        参数
        ----
        source_unit_ids
            参与叙事编织的 MemoryUnit id 列表（从 LTM 查询）
        chapter
            人生章节标签（如"系统构建早期"），用于跨章节检索
        persona_snapshot
            PersonaManager 渲染的人格上下文字符串（可选）
        emotional_context
            当前情绪状态文字（可来自 EmotionalStateBlock.render()）

        返回
        ----
        写入的 NarrativeMemory；source_unit_ids 全部无效时返回 None。
        """
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
        """从已有 unit 列表合成叙事并写入。

        适合 LifeManager 已持有 unit 对象时调用（避免二次读 DB）。

        参数
        ----
        source_units
            参与叙事编织的 MemoryUnit 实例列表
        chapter
            人生章节标签
        persona_snapshot
            人格上下文字符串（可选）
        emotional_context
            情绪状态文字（可选）

        返回
        ----
        写入的 NarrativeMemory
        """
        unit = self._extract(source_units, chapter, persona_snapshot, emotional_context)
        self._store.put(unit)
        for src in source_units:
            self._store.add_narrative_ref(src.id)
        if self._on_written is not None:
            self._on_written(unit)
        return unit

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extract(
        self,
        source_units: list[MemoryUnit],
        chapter: str,
        persona_snapshot: str,
        emotional_context: str,
    ) -> NarrativeMemory:
        memories_text = "\n".join(
            f"{i+1}. {_render_unit(u)}" for i, u in enumerate(source_units)
        )
        persona_section = (
            f"【人格背景】\n{persona_snapshot}\n\n" if persona_snapshot.strip() else ""
        )
        emotion_section = (
            f"【当前情绪状态】\n{emotional_context}\n\n" if emotional_context.strip() else ""
        )
        prompt = (
            f"{persona_section}"
            f"{emotion_section}"
            f"【章节】{chapter}\n\n"
            f"【原始记忆片段（共 {len(source_units)} 条）】\n{memories_text}\n\n"
            f"请将以上记忆编织为一段叙事记忆 JSON：\n{_SCHEMA}"
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
        return NarrativeMemory(
            focus=d.get("focus", chapter or "（未提取）"),
            narrative=d.get("narrative", ""),
            source_ids=[u.id for u in source_units],
            chapter=chapter,
            emotion=d.get("emotion", ""),
            emotion_intensity=float(d.get("emotion_intensity", 0.0)),
            valence=_valence(d.get("valence", "neutral")),
            base_activation=float(d.get("base_activation", 0.7)),
            tier=MemoryTier.long,
        )
