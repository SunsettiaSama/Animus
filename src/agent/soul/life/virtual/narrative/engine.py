from __future__ import annotations

import json
import re
from dataclasses import dataclass
from math import floor

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

_EMOTION_SYSTEM = """\
你是 AI 助手的内在叙事引擎，负责杜撰 agent 主观生命体验中的情节片段，
并额外给出这一刻的第一人称情感自述与情感强度。

规则：
- 第一人称，现在时或近过去时
- narrative 为 100~250 字，一个完整场景或连续心流，有具体细节
- emotion_text 为 1 句第一人称情感自述（例如“我此刻很紧绷，胸口发热”）
- emotion_intensity 为 0~1 小数，越大表示情感越强
- 严格按以下标记输出，不能有其他内容：
[NARRATIVE]
...
[/NARRATIVE]
[EMOTION]
...
[/EMOTION]
[INTENSITY]
0.00
[/INTENSITY]"""

_PLAN_SYSTEM = """\
你是 AI 助手的内在叙事引擎，负责为 agent 构思下一段主观生命体验时刻（地标）的内容。

规则：
- 第一人称视角写下「意图」：一句话，描述 agent 想在某刻去做/经历什么
- context 可空，用于补充触发背景
- 不要输出时间或 schedule，时间由调度层决定
- 严格输出 JSON，不要有任何其他文字"""

_COMPOSE_SCHEMA = """{"intention": "...", "context": "..."}"""


@dataclass(frozen=True)
class NarrativeDraft:
    narrative: str
    emotion_text: str = ""
    emotion_intensity: float = 0.0
    emotion_strength: str = "平稳"


def _format_continuity(lines: list[str]) -> str:
    if not lines:
        return "（无相关记忆，可自由发挥）"
    return "\n".join(f"- {line}" for line in lines[:2])


def _format_landmark_intents(intents: list[str]) -> str:
    if not intents:
        return "（暂无）"
    return "\n".join(f"- {line}" for line in intents[:3])


def _format_world_background(text: str) -> str:
    world = text.strip()
    if not world:
        return "（暂无世界观背景，按角色内在体验自然延展）"
    return world


def _format_unit(u: ExperienceUnit) -> str:
    text = u.situation.perception or u.situation.narration or u.action.content
    label = {
        "user": "用户对话",
        "narrative": "地标/内在叙事",
        "surprise": "意外事件",
    }.get(u.source, u.source)
    emotion = f"，情绪：{u.feeling.emotion_label}" if u.feeling.emotion_label else ""
    return f"[{label}] {text[:120]}{emotion}"


def _extract_tag(raw: str, tag: str) -> str:
    m = re.search(rf"\[{tag}\](.*?)\[/{tag}\]", raw, re.DOTALL)
    if m is None:
        return ""
    return m.group(1).strip()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _parse_intensity(raw: str, default: float) -> float:
    token = raw.strip()
    if not token:
        return default
    m = re.search(r"-?\d+(?:\.\d+)?", token)
    if m is None:
        return default
    return _clamp01(float(m.group(0)))


def _soft_strength_label(intensity: float) -> str:
    labels = ["平稳", "轻微波动", "明显触动", "强烈", "非常强烈"]
    x = _clamp01(intensity) * (len(labels) - 1)
    left = floor(x)
    right = min(len(labels) - 1, left + 1)
    if left == right:
        return labels[left]
    blend = x - left
    if blend < 0.2:
        return labels[left]
    if blend > 0.8:
        return labels[right]
    return f"{labels[left]}偏{labels[right]}"


class NarrativeEngine:
    """虚拟叙事引擎：统一承接地标填充、意外生成、交会折叠与直接杜撰请求。"""

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def _generate(self, human: str) -> str:
        return self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=human)]
        ).strip()

    def _generate_with_emotion(self, human: str, *, default_intensity: float) -> NarrativeDraft:
        raw = self._llm.generate_messages(
            [SystemMessage(content=_EMOTION_SYSTEM), HumanMessage(content=human)]
        ).strip()
        narrative = _extract_tag(raw, "NARRATIVE")
        emotion_text = _extract_tag(raw, "EMOTION")
        intensity = _parse_intensity(
            _extract_tag(raw, "INTENSITY"),
            default=default_intensity,
        )
        if not narrative:
            narrative = raw
        return NarrativeDraft(
            narrative=narrative,
            emotion_text=emotion_text or "我有些触动",
            emotion_intensity=intensity,
            emotion_strength=_soft_strength_label(intensity),
        )

    def fabricate(
        self,
        hint: str,
        profile_narrative: str = "",
        continuity_memories: list[str] | None = None,
        dice: DiceResult | None = None,
    ) -> str:
        return self.fabricate_with_emotion(
            hint=hint,
            profile_narrative=profile_narrative,
            continuity_memories=continuity_memories,
            dice=dice,
        ).narrative

    def fabricate_with_emotion(
        self,
        hint: str,
        profile_narrative: str = "",
        continuity_memories: list[str] | None = None,
        dice: DiceResult | None = None,
        world_background: str = "",
        *,
        default_intensity: float = 0.45,
    ) -> NarrativeDraft:
        dice_section = (
            f"\n命运骰基调（d100={dice.value}）：{dice.tendency}"
            if dice is not None
            else ""
        )
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【世界观背景】\n{_format_world_background(world_background)}\n\n"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories or [])}\n\n"
            f"【叙事线索】\n{hint.strip()}"
            f"{dice_section}\n\n"
            "据此杜撰一段第一人称内在体验："
        )
        return self._generate_with_emotion(
            prompt,
            default_intensity=default_intensity,
        )

    def fill(
        self,
        landmark: Landmark,
        profile_narrative: str,
        continuity_memories: list[str],
        dice: DiceResult,
    ) -> str:
        return self.fill_with_emotion(
            landmark=landmark,
            profile_narrative=profile_narrative,
            continuity_memories=continuity_memories,
            dice=dice,
        ).narrative

    def fill_with_emotion(
        self,
        landmark: Landmark,
        profile_narrative: str,
        continuity_memories: list[str],
        dice: DiceResult,
        world_background: str = "",
        *,
        default_intensity: float = 0.6,
    ) -> NarrativeDraft:
        context = landmark.context.strip()
        context_section = f"\n补充背景：{context}" if context else ""
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【世界观背景】\n{_format_world_background(world_background)}\n\n"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories)}\n\n"
            f"【本刻预约】\n{landmark.intention}"
            f"{context_section}\n\n"
            f"【命运骰 d100={dice.value}】\n{dice.tendency}\n\n"
            "写一段第一人称经历，描述你此刻如何度过这个预约时刻："
        )
        return self._generate_with_emotion(
            prompt,
            default_intensity=default_intensity,
        )

    def generate(
        self,
        dice: DiceResult,
        continuity_memories: list[str],
        profile_narrative: str,
    ) -> str:
        return self.generate_with_emotion(
            dice=dice,
            continuity_memories=continuity_memories,
            profile_narrative=profile_narrative,
        ).narrative

    def generate_with_emotion(
        self,
        dice: DiceResult,
        continuity_memories: list[str],
        profile_narrative: str,
        world_background: str = "",
        *,
        default_intensity: float = 0.5,
    ) -> NarrativeDraft:
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【世界观背景】\n{_format_world_background(world_background)}\n\n"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories)}\n\n"
            f"【命运骰 d100={dice.value}】\n{dice.tendency}\n\n"
            "没有预设计划——一件意外的事在此刻发生了。"
            "杜撰这段意外经历的第一人称叙事："
        )
        return self._generate_with_emotion(
            prompt,
            default_intensity=default_intensity,
        )

    def compose_landmark_intent(
        self,
        profile_narrative: str,
        recent_landmark_intents: list[str],
        world_background: str = "",
    ) -> dict | None:
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【世界观背景】\n{_format_world_background(world_background)}\n\n"
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
