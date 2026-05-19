from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM

from ...experience.unit import ExperienceUnit
from ..journal.dice import DiceResult
from ..journal.item import Landmark

_SYSTEM = """\
你是 AI 助手的内在叙事引擎，负责杜撰 agent 主观生命体验中的情节片段。

这些内容是「虚拟叙事」——描写 agent 在某个时刻的内在经历、行动与感知，
不必对应外部系统的客观日志，但应在人格与近期上下文中站得住脚。

规则：
- 第一人称，现在时或近过去时
- 100~250 字，一个完整场景或连续心流，有具体细节
- 允许虚构细节，但不要与给定上下文明显矛盾
- 严格输出纯文本，无标题、无 markdown、无 JSON、无引号包裹"""

_PLAN_SYSTEM = """\
你是 AI 助手的内在叙事引擎，负责为 agent 构思下一段主观生命体验时刻（地标）的内容。

规则：
- 第一人称视角写下「意图」：一句话，描述 agent 想在某刻去做/经历什么
- context 可空，用于补充触发背景
- 不要输出时间或 schedule，时间由调度层决定
- 严格输出 JSON，不要有任何其他文字"""

_COMPOSE_SCHEMA = """{"intention": "...", "context": "..."}"""


def _format_continuity(lines: list[str]) -> str:
    if not lines:
        return "（无相关记忆，可自由发挥）"
    return "\n".join(f"- {line}" for line in lines[:2])


def _format_landmark_intents(intents: list[str]) -> str:
    if not intents:
        return "（暂无）"
    return "\n".join(f"- {line}" for line in intents[:3])


def _format_unit(u: ExperienceUnit) -> str:
    text = u.situation.perception or u.situation.narration or u.action.content
    label = {
        "user": "用户对话",
        "narrative": "地标/内在叙事",
        "surprise": "意外事件",
    }.get(u.source, u.source)
    emotion = f"，情绪：{u.feeling.emotion_label}" if u.feeling.emotion_label else ""
    return f"[{label}] {text[:120]}{emotion}"


class NarrativeEngine:
    """虚拟叙事引擎：统一承接地标填充、意外生成、交会折叠与直接杜撰请求。"""

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def _generate(self, human: str) -> str:
        return self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=human)]
        ).strip()

    def fabricate(
        self,
        hint: str,
        profile_narrative: str = "",
        continuity_memories: list[str] | None = None,
        dice: DiceResult | None = None,
    ) -> str:
        dice_section = (
            f"\n命运骰基调（d100={dice.value}）：{dice.tendency}"
            if dice is not None
            else ""
        )
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories or [])}\n\n"
            f"【叙事线索】\n{hint.strip()}"
            f"{dice_section}\n\n"
            "据此杜撰一段第一人称内在体验："
        )
        return self._generate(prompt)

    def fill(
        self,
        landmark: Landmark,
        profile_narrative: str,
        continuity_memories: list[str],
        dice: DiceResult,
    ) -> str:
        context = landmark.context.strip()
        context_section = f"\n补充背景：{context}" if context else ""
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories)}\n\n"
            f"【本刻预约】\n{landmark.intention}"
            f"{context_section}\n\n"
            f"【命运骰 d100={dice.value}】\n{dice.tendency}\n\n"
            "写一段第一人称经历，描述你此刻如何度过这个预约时刻："
        )
        return self._generate(prompt)

    def generate(
        self,
        dice: DiceResult,
        continuity_memories: list[str],
        profile_narrative: str,
    ) -> str:
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories)}\n\n"
            f"【命运骰 d100={dice.value}】\n{dice.tendency}\n\n"
            "没有预设计划——一件意外的事在此刻发生了。"
            "杜撰这段意外经历的第一人称叙事："
        )
        return self._generate(prompt)

    def compose_landmark_intent(
        self,
        profile_narrative: str,
        recent_landmark_intents: list[str],
    ) -> dict | None:
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【近期已预约并完成的地标意图（勿重复）】\n"
            f"{_format_landmark_intents(recent_landmark_intents)}\n\n"
            f"构思下一个不同的内在体验时刻，输出 JSON：\n{_COMPOSE_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_PLAN_SYSTEM), HumanMessage(content=prompt)]
        ).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        intention = str(d.get("intention", "")).strip()
        if not intention:
            return None
        return {
            "intention": intention,
            "context": str(d.get("context", "")).strip(),
        }

    def collapse(self, units: list[ExperienceUnit]) -> str:
        parts = "\n".join(f"- {_format_unit(u)}" for u in units)
        prompt = (
            "以下几段体验在相近时刻发生，实际交织在同一段连续意识里：\n"
            f"{parts}\n\n"
            "将它们重新表述为一段统一的第一人称经历，"
            "写清这些事交会时实际发生了什么（100~250字）："
        )
        return self._generate(prompt)
