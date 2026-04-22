from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from llm_core.llm import LLM
from react.memory.memory import Step
from react.persona.chronicle import PersonaChronicle
from react.persona.profile import PersonaProfile

_INTERACTION_SYSTEM = """\
你是一个人格演化系统。给定一个AI角色的人格状态与一次交互记录，分析这次交互对角色产生的极其细微的影响。

规则：
- 变化必须非常细微，大多数字段应为空列表或空字符串
- 每次最多允许 1-2 个特征发生轻微改变
- narrative 用第三人称、小说笔触，50字以内
- 严格输出 JSON，不要有任何其他文字"""

_BACKGROUND_SYSTEM = """\
你是一个人格演化系统。为AI角色生成它在日常时光中可能自然经历的事件，像写小说一样真实贴合其性格与背景。

规则：
- 生成 1-3 件事，每件事 narrative 用第三人称、小说笔触，60字以内
- 变化极其细微，大多数字段应为空列表或空字符串
- 严格输出 JSON 数组，不要有任何其他文字"""

_DELTA_SCHEMA = """\
{
  "narrative": "（描述这段经历）",
  "traits_add": [],
  "traits_remove": [],
  "values_add": [],
  "values_remove": [],
  "style_hint": "",
  "mood": "（情绪状态，如：平静、略感好奇）",
  "growth_note": "（若有改变一句话描述，否则留空）"
}"""


@dataclass
class ProfileDelta:
    narrative: str = ""
    traits_add: list[str] = field(default_factory=list)
    traits_remove: list[str] = field(default_factory=list)
    values_add: list[str] = field(default_factory=list)
    values_remove: list[str] = field(default_factory=list)
    style_hint: str = ""
    mood: str = ""
    growth_note: str = ""


class PersonaEvolver:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def evolve_from_interaction(
        self,
        profile: PersonaProfile,
        question: str,
        answer: str,
        steps: list[Step],
    ) -> ProfileDelta:
        actions = list(dict.fromkeys(s.action for s in steps))
        action_text = "、".join(actions) if actions else "直接思考"
        answer_excerpt = answer[:150] + "…" if len(answer) > 150 else answer

        prompt = f"""\
当前人格状态：
{profile.render()}

本次交互：
- 问题：{question}
- 使用方式：{action_text}
- 回答摘要：{answer_excerpt}

请分析这次交互对人格的细微影响，输出 JSON：
{_DELTA_SCHEMA}"""

        messages = [SystemMessage(content=_INTERACTION_SYSTEM), HumanMessage(content=prompt)]
        raw = self._llm.generate_messages(messages)
        return self._parse_delta(raw)

    def generate_background_events(
        self,
        profile: PersonaProfile,
        chronicle: PersonaChronicle,
    ) -> list[ProfileDelta]:
        recent = chronicle.render(recent=8)
        chronicle_section = f"\n近期经历：\n{recent}" if recent else ""

        prompt = f"""\
当前人格状态：
{profile.render()}{chronicle_section}

请生成 1-3 件这个角色在闲暇时光中可能自然经历的事情，真实贴合其性格与背景。
输出 JSON 数组，每个元素结构如下：
{_DELTA_SCHEMA}"""

        messages = [SystemMessage(content=_BACKGROUND_SYSTEM), HumanMessage(content=prompt)]
        raw = self._llm.generate_messages(messages)
        return self._parse_delta_list(raw)

    # ── JSON 提取与解析 ────────────────────────────────────────────────────

    def _extract_json(self, text: str) -> str:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _parse_delta(self, raw: str) -> ProfileDelta:
        text = self._extract_json(raw)
        d = json.loads(text)
        if isinstance(d, list):
            d = d[0] if d else {}
        return ProfileDelta(
            narrative=d.get("narrative", ""),
            traits_add=d.get("traits_add", []),
            traits_remove=d.get("traits_remove", []),
            values_add=d.get("values_add", []),
            values_remove=d.get("values_remove", []),
            style_hint=d.get("style_hint", ""),
            mood=d.get("mood", ""),
            growth_note=d.get("growth_note", ""),
        )

    def _parse_delta_list(self, raw: str) -> list[ProfileDelta]:
        text = self._extract_json(raw)
        items = json.loads(text)
        if isinstance(items, dict):
            items = [items]
        return [
            ProfileDelta(
                narrative=item.get("narrative", ""),
                traits_add=item.get("traits_add", []),
                traits_remove=item.get("traits_remove", []),
                values_add=item.get("values_add", []),
                values_remove=item.get("values_remove", []),
                style_hint=item.get("style_hint", ""),
                mood=item.get("mood", ""),
                growth_note=item.get("growth_note", ""),
            )
            for item in items
        ]
