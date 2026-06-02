from __future__ import annotations

import json
import re
from dataclasses import dataclass
from math import floor

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.voice_rules import YOU_VOICE_RULES
from infra.llm import BaseLLM

from ...experience.domain.unit import ExperienceUnit
from storyview.fate.dice import DiceResult
from ..journal.item import Landmark

_SYSTEM = f"""\
你是内在生命体验叙事引擎，负责杜撰 Agent 虚拟生命体验中的情节片段。

这些内容是「虚拟叙事」——描写你在某个时刻的经历、行动与感知，
不必对应外部客观日志，但应在人格与近期上下文中站得住脚。

{YOU_VOICE_RULES}

规则：
- 现在时或近过去时；100~250 字，一个完整场景或连续心流，有具体细节
- 允许虚构细节，但不要与给定上下文明显矛盾
- 严格输出纯文本，无标题、无 markdown、无 JSON、无引号包裹"""

_EMOTION_SYSTEM = f"""\
你是内在生命体验叙事引擎，负责杜撰虚拟生命体验片段，并给出这一刻的情感自述与强度。

{YOU_VOICE_RULES}

规则：
- narrative：100~250 字，客观叙述你在做什么、发生什么为主，穿插少量你的感受
- emotion_text：1 句「你」的情感自述（例如「你此刻很紧绷，胸口发热」）
- emotion_intensity：0~1 小数，越大表示情感越强
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

_PLAN_SYSTEM = f"""\
你是内在生命体验叙事引擎，负责为你构思下一段生命体验时刻（地标）的内容。

{YOU_VOICE_RULES}

规则：
- intention：第二人称「你」一句话，客观描述你想在某刻去做/经历什么，可少许动机感受
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


def _format_objective_scene(text: str) -> str:
    scene = text.strip()
    if not scene:
        return ""
    return f"【客观场景（世界规则，第二人称）】\n{scene}\n\n"


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
        objective_scene: str = "",
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
            f"{_format_objective_scene(objective_scene)}"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories or [])}\n\n"
            f"【叙事线索】\n{hint.strip()}"
            f"{dice_section}\n\n"
            "据此杜撰一段以「你」叙述的内在体验（客观为主，少许感受）："
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
        dice: DiceResult | None = None,
        world_background: str = "",
        objective_scene: str = "",
        *,
        default_intensity: float = 0.6,
    ) -> NarrativeDraft:
        context = landmark.context.strip()
        context_section = f"\n补充背景：{context}" if context else ""
        dice_section = (
            f"\n【命运骰 d100={dice.value}】\n{dice.tendency}\n"
            if dice is not None
            else ""
        )
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【世界观背景】\n{_format_world_background(world_background)}\n\n"
            f"{_format_objective_scene(objective_scene)}"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories)}\n\n"
            f"【本刻预约】\n{landmark.intention}"
            f"{context_section}"
            f"{dice_section}\n"
            "写一段以「你」叙述的经历，客观描述你此刻如何度过这个预约时刻，末尾可少许感受："
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
            continuity_memories=continuity_memories,
            profile_narrative=profile_narrative,
            dice=dice,
        ).narrative

    def generate_with_emotion(
        self,
        continuity_memories: list[str],
        profile_narrative: str,
        *,
        dice: DiceResult | None = None,
        world_background: str = "",
        objective_scene: str = "",
        default_intensity: float = 0.5,
    ) -> NarrativeDraft:
        dice_section = (
            f"\n【命运骰 d100={dice.value}】\n{dice.tendency}\n"
            if dice is not None
            else ""
        )
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【世界观背景】\n{_format_world_background(world_background)}\n\n"
            f"{_format_objective_scene(objective_scene)}"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories)}\n\n"
            f"{dice_section}"
            "没有预设计划——一件意外的事在此刻发生了。"
            "杜撰这段意外经历：以「你」客观叙述为主，穿插少许你的感受："
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
            "将它们重新表述为一段统一的「你」的经历，"
            "客观写清交会时实际发生了什么，末尾可少许你的感受（100~250字）："
        )
        return self._generate(prompt)
