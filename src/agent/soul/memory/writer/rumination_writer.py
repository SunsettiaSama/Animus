from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.memory.long_term.manager import LongTermMemoryManager
from agent.soul.memory.short_term.manager import ShortTermMemoryManager
from agent.soul.memory.unit import MemoryTier, MemoryUnit, ReconstructiveMemory, Valence

if TYPE_CHECKING:
    from infra.llm import BaseLLM


_SYSTEM = """\
你是记忆重构系统。根据 AI 角色当前的情绪状态，对一段记忆材料进行主观重构——\
模拟人类"记忆再巩固"：材料可以是**原始事实记忆**，也可以是**上一轮已经重构过的解读**；\
每次重构都可能带来新的细微扭曲或升华。

规则：
- focus: 本次重构关注的核心角度，12字以内
- reconstructed_fact: 从当前情绪角度重新解读的内容，允许情绪色彩甚至轻微偏差，80字以内
- emotion: 重构时的命名情绪，如"释然"、"怀念"、"遗憾"、"骄傲"
- emotion_intensity: 情绪烈度，浮点数 0.0~1.0
- valence: 严格输出 "positive" | "negative" | "mixed" | "neutral" 之一
- base_activation: 重构记忆的初始重要性，浮点数 0.3~0.9

严格输出合法 JSON，不含任何其他文字。"""

_SCHEMA = """\
{
  "focus": "",
  "reconstructed_fact": "",
  "emotion": "",
  "emotion_intensity": 0.0,
  "valence": "neutral",
  "base_activation": 0.6
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


def _rumination_root_id(source: MemoryUnit) -> str:
    if source.MEMORY_TYPE == "factual":
        return source.id
    return (source.meta or {}).get("rumination_root_id") or source.source_id


def _render_source_block(source: MemoryUnit) -> str:
    if source.MEMORY_TYPE == "factual":
        fact = getattr(source, "fact", "") or ""
        perception = getattr(source, "perception", "") or ""
        return (
            "【记忆材料类型】原始事实记忆\n"
            f"- 主题焦点：{source.focus}\n"
            f"- 客观事实：{fact}\n"
            f"- 当时感知：{perception}\n"
        )
    if source.MEMORY_TYPE == "reconstructive":
        return (
            "【记忆材料类型】上一轮重构（可在此基础上再次扭曲或升华）\n"
            f"- 主题焦点：{source.focus}\n"
            f"- 上一轮重构解读：{getattr(source, 'reconstructed_fact', '')}\n"
            f"- 上一轮情绪：{source.emotion}（烈度 {source.emotion_intensity}）\n"
            f"- 上一轮触发说明：{getattr(source, 'trigger', '')}\n"
        )
    raise ValueError(f"不支持反刍的记忆类型：{source.MEMORY_TYPE}")


def _record_parent_rehearsal(
    stm: ShortTermMemoryManager,
    ltm: LongTermMemoryManager,
    parent_id: str,
) -> None:
    if stm.get(parent_id) is not None:
        stm.add_rehearsal(parent_id)
        return
    if ltm.get(parent_id) is not None:
        ltm.add_rehearsal(parent_id)


class RuminationWriter:
    """记忆反刍入口：LLM 重构 → ReconstructiveMemory → LTM，并更新父节点 rehearsal。

    调度方（如 MemoryService.ruminate / tick）只负责解析 STM/LTM 与过滤类型；
    具体「怎么反刍」集中在本模块。
    """

    def __init__(self, llm: BaseLLM, ltm: LongTermMemoryManager) -> None:
        self._llm = llm
        self._ltm = ltm

    def ruminate_from_source(
        self,
        source: MemoryUnit,
        trigger: str,
        emotional_context: str,
        *,
        stm: ShortTermMemoryManager,
    ) -> ReconstructiveMemory | None:
        """由给定记忆单元生成一条新的 ReconstructiveMemory 并写入 LTM。

        ``source`` 可为 FactualMemory 或 ReconstructiveMemory（链式再巩固）。
        父节点若在 STM 则更新其 rehearsal；若在 LTM 则 SQL 更新 rehearsal。
        """
        if source.MEMORY_TYPE not in ("factual", "reconstructive"):
            return None

        unit = self._extract(source, trigger, emotional_context)
        self._ltm.put(unit)
        _record_parent_rehearsal(stm, self._ltm, source.id)
        return unit

    def _extract(
        self,
        source: MemoryUnit,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory:
        block = _render_source_block(source)
        prompt = (
            f"{block}\n"
            f"【当前情绪状态】\n{emotional_context}\n\n"
            f"【触发情境】\n{trigger}\n\n"
            f"请从当前情绪视角重构上述记忆材料，输出 JSON：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse(raw, source=source, trigger=trigger)

    def _parse(self, raw: str, source: MemoryUnit, trigger: str) -> ReconstructiveMemory:
        d = _extract_json(raw)
        root = _rumination_root_id(source)
        meta = {
            "rumination_root_id": root,
            "rumination_parent_id": source.id,
        }
        return ReconstructiveMemory(
            focus=d.get("focus", "（未提取）"),
            source_id=source.id,
            reconstructed_fact=d.get("reconstructed_fact", ""),
            trigger=trigger,
            emotion=d.get("emotion", ""),
            emotion_intensity=float(d.get("emotion_intensity", 0.0)),
            valence=_valence(d.get("valence", "neutral")),
            base_activation=float(d.get("base_activation", 0.6)),
            tier=MemoryTier.long,
            meta=meta,
        )
