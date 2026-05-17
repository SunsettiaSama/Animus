from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.memory.unit import FactualMemory, MemoryTier, Valence

if TYPE_CHECKING:
    from infra.llm import BaseLLM
    from agent.soul.memory.short_term.manager import ShortTermMemoryManager
    from agent.soul.memory.long_term.manager import LongTermMemoryManager


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """\
你是记忆提炼系统。根据 AI 角色的人格背景与一次完整对话，提炼出一条事实性记忆单元。

规则：
- focus: 记忆的语义锚点，12字以内，概括这次对话的核心主题
- fact: 客观陈述发生了什么，不含主观情绪，80字以内
- perception: Agent 第一人称的主观体验叙述，允许模糊、复杂、矛盾，50~100字
- emotion: 命名情绪，如"焦虑"、"好奇"、"释然"、"矛盾"；若无明显情绪则留空字符串
- emotion_intensity: 情绪烈度，浮点数 0.0~1.0（0=无情绪，1=极度强烈）
- valence: 情感倾向，严格输出 "positive" | "negative" | "mixed" | "neutral" 之一
- base_activation: 这条记忆的初始重要性，浮点数 0.2~1.0

严格输出合法 JSON，不含任何其他文字。"""

_SCHEMA = """\
{
  "focus": "",
  "fact": "",
  "perception": "",
  "emotion": "",
  "emotion_intensity": 0.0,
  "valence": "neutral",
  "base_activation": 0.5
}"""

def _extract_json(raw: str) -> dict:
    """从 LLM 输出中提取第一个合法 JSON 对象。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"LLM 输出中未找到合法 JSON：{raw[:200]}")


def _valence(v: str) -> Valence:
    try:
        return Valence(v)
    except ValueError:
        return Valence.neutral


class TurnWriter:
    """实时对话记忆写入器。

    每轮对话结束后由 MemoryService.ingest_turn() 调用（通常在后台线程），
    流程：

    1. 将 Q&A + 人格快照拼装 prompt，调用 LLM 提取记忆字段
    2. 构造 FactualMemory
    3. 写入 ShortTermMemoryManager（Redis）
    4. 若 emotion_intensity 超过高情绪阈值，直接同步晋升 LongTermMemoryManager（MySQL）

    参数
    ----
    llm
        底层推理实例（BaseLLM），支持 generate_messages()
    stm
        短期记忆管理器（Redis）
    ltm
        长期记忆管理器（MySQL），用于高情绪记忆的即时晋升
    promote_threshold
        emotion_intensity 超过此值时直接晋升长期记忆，默认 0.7
    """

    def __init__(
        self,
        llm: BaseLLM,
        stm: ShortTermMemoryManager,
        ltm: LongTermMemoryManager,
        promote_threshold: float = 0.7,
    ) -> None:
        self._llm = llm
        self._stm = stm
        self._ltm = ltm
        self._threshold = promote_threshold

    def write(
        self,
        question: str,
        answer: str,
        persona_snapshot: str = "",
    ) -> FactualMemory:
        """提炼并写入一条事实性记忆，返回已写入的 FactualMemory 实例。

        参数
        ----
        question
            用户问题（原文）
        answer
            Agent 本轮回答（原文，过长时内部截断）
        persona_snapshot
            PersonaManager 渲染的人格上下文字符串（可选）；
            传入后 LLM 可以结合角色身份给出更准确的主观感知。
        """
        unit = self._extract(question, answer, persona_snapshot)
        self._stm.put(unit)

        if unit.emotion_intensity >= self._threshold:
            unit.promote_to_long()
            self._ltm.put(unit)

        return unit

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extract(
        self,
        question: str,
        answer: str,
        persona_snapshot: str,
    ) -> FactualMemory:
        answer_excerpt = answer[:300] + "…" if len(answer) > 300 else answer
        persona_section = (
            f"【人格背景】\n{persona_snapshot}\n\n" if persona_snapshot.strip() else ""
        )
        prompt = (
            f"{persona_section}"
            f"【对话内容】\n"
            f"- 用户问题：{question}\n"
            f"- Agent 回答摘要：{answer_excerpt}\n\n"
            f"请输出事实性记忆单元 JSON：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse(raw)

    def _parse(self, raw: str) -> FactualMemory:
        d = _extract_json(raw)
        return FactualMemory(
            focus=d.get("focus", "（未提取）"),
            fact=d.get("fact", ""),
            perception=d.get("perception", ""),
            emotion=d.get("emotion", ""),
            emotion_intensity=float(d.get("emotion_intensity", 0.0)),
            valence=_valence(d.get("valence", "neutral")),
            base_activation=float(d.get("base_activation", 0.5)),
            tier=MemoryTier.short_term,
        )
