from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from llm_core.llm import BaseLLM
from ...memory.memory import Step
from ...persona.profile.profile import PersonaProfile
from ...persona.profile.skills import Skill, SkillsLibrary

# ── System prompts ─────────────────────────────────────────────────────────────

_PROFILE_SYSTEM = """\
你是一个人格演化系统。给定 AI 角色的当前人格状态与一次交互记录，\
分析这次交互对角色产生的极其细微的影响。

规则：
- 变化必须非常细微，大多数字段应为空列表或空字符串
- 每次最多允许 1-2 个特征发生轻微改变
- narrative 用第三人称、小说笔触，50 字以内
- 严格输出 JSON，不要有任何其他文字"""

_SKILLS_SYSTEM = """\
你是一个技能演化系统。根据 AI 角色的人格画像与一次交互记录，\
判断技能库是否需要更新——新增技能、调整描述或移除已无意义的技能。

规则：
- 优先考虑"不变化"，除非有充分理由
- 新增技能的 priority 在 3-8 之间
- 严格输出 JSON，不要有任何其他文字"""

_REFLECT_SYSTEM = """\
你是一个自省系统。根据 AI 角色的人格画像与技能库，\
生成一段第一人称的自我感知表述，概括当前行为倾向与内在状态。

规则：
- 第一人称，60-150 字
- 自然流畅，体现角色当前的情绪基调与行为模式
- 严格输出纯文本，无任何格式标记"""

_PROFILE_DELTA_SCHEMA = """\
{
  "narrative": "（描述这段经历，50字以内）",
  "traits_add": [],
  "traits_remove": [],
  "values_add": [],
  "values_remove": [],
  "style_hint": "",
  "mood": "（情绪状态，如：平静、略感好奇）",
  "growth_note": "（若有改变一句话描述，否则留空）"
}"""

_SKILLS_DELTA_SCHEMA = """\
{
  "add": [
    {"name": "技能名称", "description": "技能描述", "trigger": "触发条件", "priority": 5}
  ],
  "update": [
    {"name": "已有技能名称", "description": "新描述", "priority": 6}
  ],
  "remove": ["无意义的技能名称"]
}"""


# ── Delta dataclasses ──────────────────────────────────────────────────────────

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


@dataclass
class SkillDelta:
    add: list[dict] = field(default_factory=list)
    update: list[dict] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)


# ── Evolver ───────────────────────────────────────────────────────────────────

class PersonaEvolver:
    """LLM 驱动的三层演化器：人格画像 / 技能库 / 自省。"""

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    # ── Profile evolution ──────────────────────────────────────────────────────

    def evolve_profile(
        self,
        profile: PersonaProfile,
        question: str,
        answer: str,
        steps: list[Step],
    ) -> ProfileDelta:
        actions = list(dict.fromkeys(s.action for s in steps))
        action_text = "、".join(actions) if actions else "直接思考"
        answer_excerpt = answer[:150] + "…" if len(answer) > 150 else answer

        prompt = (
            f"当前人格状态：\n{profile.render()}\n\n"
            f"本次交互：\n"
            f"- 问题：{question}\n"
            f"- 使用方式：{action_text}\n"
            f"- 回答摘要：{answer_excerpt}\n\n"
            f"请分析这次交互对人格的细微影响，输出 JSON：\n{_PROFILE_DELTA_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_PROFILE_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse_profile_delta(raw)

    # ── Skills evolution ───────────────────────────────────────────────────────

    def evolve_skills(
        self,
        profile: PersonaProfile,
        skills: SkillsLibrary,
        question: str,
        answer: str,
        steps: list[Step],
    ) -> SkillDelta:
        actions = list(dict.fromkeys(s.action for s in steps))
        action_text = "、".join(actions) if actions else "直接思考"
        answer_excerpt = answer[:120] + "…" if len(answer) > 120 else answer
        current = skills.render(top_k=len(skills.skills)) if skills.skills else "（当前无技能）"

        prompt = (
            f"当前人格状态：\n{profile.render()}\n\n"
            f"当前技能库：\n{current}\n\n"
            f"本次交互：\n"
            f"- 问题：{question}\n"
            f"- 使用方式：{action_text}\n"
            f"- 回答摘要：{answer_excerpt}\n\n"
            f"请判断技能库是否需要更新，输出 JSON：\n{_SKILLS_DELTA_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SKILLS_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse_skill_delta(raw)

    # ── Self-reflection (IROTE) ────────────────────────────────────────────────

    def reflect(
        self,
        profile: PersonaProfile,
        skills: SkillsLibrary,
    ) -> str:
        skills_section = f"\n当前技能：\n{skills.render(top_k=5)}" if len(skills) > 0 else ""

        prompt = (
            f"角色画像：\n{profile.render()}"
            f"{skills_section}\n\n"
            "请以第一人称生成自我感知表述（60-150字）："
        )
        return self._llm.generate_messages(
            [SystemMessage(content=_REFLECT_SYSTEM), HumanMessage(content=prompt)]
        ).strip()

    # ── JSON parsing ───────────────────────────────────────────────────────────

    def _extract_json(self, text: str) -> str:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            return m.group(1).strip()
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if m:
            return m.group(1).strip()
        return text.strip()

    def _parse_profile_delta(self, raw: str) -> ProfileDelta:
        d = json.loads(self._extract_json(raw))
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

    def _parse_profile_delta_list(self, raw: str) -> list[ProfileDelta]:
        items = json.loads(self._extract_json(raw))
        if isinstance(items, dict):
            items = [items]
        return [
            ProfileDelta(
                narrative=it.get("narrative", ""),
                traits_add=it.get("traits_add", []),
                traits_remove=it.get("traits_remove", []),
                values_add=it.get("values_add", []),
                values_remove=it.get("values_remove", []),
                style_hint=it.get("style_hint", ""),
                mood=it.get("mood", ""),
                growth_note=it.get("growth_note", ""),
            )
            for it in items
        ]

    def _parse_skill_delta(self, raw: str) -> SkillDelta:
        d = json.loads(self._extract_json(raw))
        if isinstance(d, list):
            d = {}
        return SkillDelta(
            add=d.get("add", []),
            update=d.get("update", []),
            remove=d.get("remove", []),
        )
