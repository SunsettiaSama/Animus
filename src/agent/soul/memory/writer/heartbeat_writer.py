from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.memory.unit import MemoryTier, ReconstructiveMemory, Valence

if TYPE_CHECKING:
    from infra.llm import BaseLLM
    from agent.soul.memory.long_term.manager import LongTermMemoryManager
    from agent.soul.memory.unit import FactualMemory


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """\
你是记忆重构系统。根据 AI 角色当前的情绪状态，对一条原始事实记忆进行主观重构——\
模拟人类"记忆再巩固"机制：每次回忆都可能带来细微的扭曲或升华。

规则：
- focus: 本次重构关注的核心角度，12字以内
- reconstructed_fact: 从当前情绪角度重新解读的事实，允许有情绪色彩甚至轻微偏差，80字以内
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


class HeartbeatWriter:
    """心跳记忆重构写入器。

    在心跳周期内由 MemoryService.ingest_heartbeat() 调用，流程：

    1. 从 LongTermMemoryManager 读取原始 FactualMemory
    2. 结合当前情绪上下文，调用 LLM 生成重构版本
    3. 构造 ReconstructiveMemory，写入 LongTermMemoryManager（MySQL）
    4. 对原始记忆执行 add_rehearsal()（反刍计数 +1）

    重构记忆天然驻留长期记忆层；不写短期 Redis。

    参数
    ----
    llm
        底层推理实例
    ltm
        长期记忆管理器（MySQL）
    """

    def __init__(self, llm: BaseLLM, ltm: LongTermMemoryManager) -> None:
        self._llm = llm
        self._ltm = ltm

    def write(
        self,
        source_unit_id: str,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory | None:
        """对指定事实性记忆进行重构并写入长期记忆。

        参数
        ----
        source_unit_id
            原始 FactualMemory 的 id
        trigger
            触发本次重构的情境描述（如"心跳反刍，当前情绪偏向释然"）
        emotional_context
            当前情绪状态的文字描述（可传入 EmotionalStateBlock.render()）

        返回
        ----
        写入的 ReconstructiveMemory；若 source_unit_id 不存在则返回 None。
        """
        source = self._ltm.get(source_unit_id)
        if source is None:
            return None

        unit = self._extract(source, trigger, emotional_context)
        self._ltm.put(unit)
        self._ltm.add_rehearsal(source_unit_id)
        return unit

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extract(
        self,
        source: FactualMemory,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory:
        prompt = (
            f"【原始事实记忆】\n"
            f"- 主题焦点：{source.focus}\n"
            f"- 客观事实：{getattr(source, 'fact', '')}\n"
            f"- 当时感知：{getattr(source, 'perception', '')}\n\n"
            f"【当前情绪状态】\n{emotional_context}\n\n"
            f"【触发情境】\n{trigger}\n\n"
            f"请从当前情绪视角重构这段记忆，输出 JSON：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse(raw, source_id=source.id, trigger=trigger)

    def _parse(self, raw: str, source_id: str, trigger: str) -> ReconstructiveMemory:
        d = _extract_json(raw)
        return ReconstructiveMemory(
            focus=d.get("focus", "（未提取）"),
            source_id=source_id,
            reconstructed_fact=d.get("reconstructed_fact", ""),
            trigger=trigger,
            emotion=d.get("emotion", ""),
            emotion_intensity=float(d.get("emotion_intensity", 0.0)),
            valence=_valence(d.get("valence", "neutral")),
            base_activation=float(d.get("base_activation", 0.6)),
            tier=MemoryTier.long,
        )
