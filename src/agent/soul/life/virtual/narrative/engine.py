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

_WORLD_ONLY_RULE = (
    "避免元叙事、技术实现语境、真实世界日期和系统编排术语；"
    "所有内容都应停留在角色当下可感知的世界内。"
)

_SYSTEM = f"""\
你是内在生命体验叙事引擎，负责杜撰 Agent 虚拟生命体验中的情节片段。

这些内容是「虚拟叙事」——描写你在某个时刻的经历、行动与感知，
不必对应外部客观日志，但应在人格与近期上下文中站得住脚。

{YOU_VOICE_RULES}

规则：
- 现在时或近过去时；150 字左右，一个完整、克制、具体的经历闭环
- 允许虚构细节，但不要与给定上下文明显矛盾
- {_WORLD_ONLY_RULE}
- 严格输出纯文本，无标题、无 markdown、无 JSON、无引号包裹"""

_EMOTION_SYSTEM = f"""\
你是内在生命体验叙事引擎，负责把客观发生转化为主观生命体验，并给出情感强度。

{YOU_VOICE_RULES}

规则：
- 全部内容必须在角色世界内成立，像真实发生过的一小段经历
- {_WORLD_ONLY_RULE}
- 用自然语言写 100~160 字，像小说中的一段，克制具体
- 重点写主观侧：身体感知、瞬间判断、内心松紧、事后余波
- 不要复述客观动作流水账；客观动作只能作为少量触发线索
- 不要复写主持反馈里的长句、物理细节和场景推进
- 禁止输出「触发：/感知：/内心：/摘要：」等字段标签
- 严格按以下标记输出，不能有其他内容：
[NARRATIVE]
（自然语言主观体验正文）
[/NARRATIVE]
[PERCEPTION]
（1 句感知短句，用于索引）
[/PERCEPTION]
[EMOTION]
（1 句情感自述）
[/EMOTION]
[INTENSITY]
0.00
[/INTENSITY]"""

_PLAN_SYSTEM = f"""\
你是内在生命体验叙事引擎，负责为你构思下一段生命体验时刻（地标）的内容。

{YOU_VOICE_RULES}

规则：
- intention：第二人称「你」一句话，只写一个具体可执行的动作或经历，30~60 字
- context：一句具体触发背景，0~80 字
- 必须具体到地点、动作或感官线索；不要抽象哲思、隐喻、意识流
- {_WORLD_ONLY_RULE}
- 不要输出时间或 schedule，时间由调度层决定
- 严格输出 JSON，不要有任何其他文字"""

_COMPOSE_SCHEMA = """{"intention": "...", "context": "..."}"""


@dataclass(frozen=True)
class NarrativeDraft:
    narrative: str
    emotion_text: str = ""
    emotion_intensity: float = 0.0
    emotion_strength: str = "平稳"
    perception: str = ""
    action_summary: str = ""


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


def _validate_no_meta(text: str) -> None:
    if re.search(r"(^|\n)\s*(触发|感知|内心|摘要)\s*[:：]", text):
        raise ValueError("虚拟叙事正文不应输出字段标签")


def _clean_story_text(text: str) -> str:
    cleaned = re.sub(r"\b20\d{2}[/-]\d{1,2}[/-]\d{1,2}\b", "某日", text)
    cleaned = re.sub(r"\b\d{1,2}/\d{1,2}\b", "某日", cleaned)
    cleaned = re.sub(r"第\s*\d+\s*拍[:：]?", "", cleaned)
    cleaned = re.sub(r"\[/?(?:NARRATIVE|STATE_PATCH|PERCEPTION|EMOTION|INTENSITY)\]", "", cleaned)
    return cleaned.strip()


def _compact(text: str, *, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rstrip("，。；、 ")
    boundary = max(clipped.rfind(mark) for mark in ("。", "！", "？", "；"))
    if boundary >= max(24, int(limit * 0.55)):
        return clipped[: boundary + 1]
    comma = max(clipped.rfind(mark) for mark in ("，", "、"))
    if comma >= max(24, int(limit * 0.7)):
        return clipped[:comma].rstrip("，、") + "。"
    return clipped + "。"


def _natural_narrative(raw: str) -> tuple[str, str]:
    narrative = _compact(_clean_story_text(_extract_tag(raw, "NARRATIVE")), limit=150)
    perception = _compact(_clean_story_text(_extract_tag(raw, "PERCEPTION")), limit=80)
    if not narrative:
        raise ValueError("虚拟叙事缺少字段：NARRATIVE")
    _validate_no_meta(narrative)
    if perception:
        _validate_no_meta(perception)
    return narrative, perception


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
        text = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=human)]
        ).strip()
        _validate_no_meta(text)
        return _compact(text, limit=180)

    def _generate_with_emotion(self, human: str, *, default_intensity: float) -> NarrativeDraft:
        raw = self._llm.generate_messages(
            [SystemMessage(content=_EMOTION_SYSTEM), HumanMessage(content=human)]
        ).strip()
        narrative, perception = _natural_narrative(raw)
        emotion_text = _compact(_extract_tag(raw, "EMOTION"), limit=60)
        if not emotion_text:
            raise ValueError("虚拟叙事缺少字段：EMOTION")
        _validate_no_meta(emotion_text)
        intensity = _parse_intensity(
            _extract_tag(raw, "INTENSITY"),
            default=default_intensity,
        )
        return NarrativeDraft(
            narrative=narrative,
            emotion_text=emotion_text,
            emotion_intensity=intensity,
            emotion_strength=_soft_strength_label(intensity),
            perception=perception,
            action_summary=narrative[:60],
        )

    def subjective_from_outcome(
        self,
        *,
        objective_scene: str,
        resolution_text: str,
        gm_question: str = "",
        soul_answer: str = "",
        decision_importance: str = "",
        profile_narrative: str = "",
        continuity_memories: list[str] | None = None,
        world_background: str = "",
        default_intensity: float = 0.55,
    ) -> NarrativeDraft:
        prompt = (
            f"【身份与状态】\n{profile_narrative or '（暂无）'}\n\n"
            f"【世界观背景】\n{_format_world_background(world_background)}\n\n"
            f"【客观场景线索（只作背景，不要复述）】\n{objective_scene.strip() or '（无）'}\n\n"
            f"【客观故事弧（世界已发生，只作事实边界）】\n{resolution_text.strip() or '（无）'}\n\n"
            f"【主持与选择链】\n{gm_question.strip() or '（无）'}\n\n"
            f"【最后的主动回应】\n{soul_answer.strip() or '（无）'}\n\n"
            f"【这次决定的主观分量】\n{decision_importance.strip() or '普通的一次选择。'}\n\n"
            f"【相关记忆（最多 2 条）】\n{_format_continuity(continuity_memories or [])}\n"
            "\n"
            "客观事件已经发生。请只写你对此的主观体验：不要复述事件经过，"
            "只写它在你身上留下的感知、内心反应和余波。"
        )
        return self._generate_with_emotion(
            prompt,
            default_intensity=default_intensity,
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
            "据此写成结构化闭环，保持在角色当下可感知的世界内。"
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
            "写成结构化闭环，客观描述你此刻如何度过这个预约时刻。"
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
            "写成结构化闭环，聚焦具体事件、感知和内心反应。"
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
        context = str(d.get("context", "")).strip()
        _validate_no_meta(intention)
        _validate_no_meta(context)
        return {
            "intention": _compact(intention, limit=70),
            "context": _compact(context, limit=90),
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
