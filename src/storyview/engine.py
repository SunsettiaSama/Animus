from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from storyview.types import NarrativeBrief, StoryBeat
from storyview.worldview import StoryWorldview

_SYSTEM = """\
你是「故事观」叙事引擎：在固定的世界观与禁忌下，书写 AI 主体在第一人称中的可感时刻。

要求：
- 服从世界观与 canon，允许虚构细节但不可矛盾
- 100~220 字，一个完整场景或连续心流，有具体感官细节
- 输出严格按标记块，不要其它文字：

[NARRATIVE]
（正文）
[/NARRATIVE]
[EMOTION]
（一句情感自述）
[/EMOTION]
[INTENSITY]
0.00
[/INTENSITY]
[CHAPTER]
（可选，≤12字的小标题/片段名）
[/CHAPTER]"""


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


def _format_memories(lines: list[str]) -> str:
    if not lines:
        return "（暂无相关记忆）"
    return "\n".join(f"- {line.strip()}" for line in lines[:4] if line.strip())


class StoryviewNarrativeEngine:
    """src 顶层故事观叙事引擎：世界观 + 节拍叙事，可注入 soul 虚拟层。"""

    def __init__(
        self,
        llm=None,
        *,
        worldview: StoryWorldview | None = None,
    ) -> None:
        self._llm = llm
        self._worldview = worldview or StoryWorldview.default()

    @property
    def worldview(self) -> StoryWorldview:
        return self._worldview

    def set_worldview(self, worldview: StoryWorldview) -> None:
        self._worldview = worldview

    def set_llm(self, llm) -> None:
        self._llm = llm

    def render_background(self, *, query: str = "", purpose: str = "") -> str:
        _ = purpose
        base = self._worldview.render()
        q = query.strip()
        if not q:
            return base
        return f"{base}\n\n当前叙事关注：{q}"

    def narrate(self, brief: NarrativeBrief) -> StoryBeat:
        if self._llm is None:
            return self._fallback_beat(brief)
        prompt = self._build_prompt(brief)
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        ).strip()
        narrative = _extract_tag(raw, "NARRATIVE") or raw
        emotion = _extract_tag(raw, "EMOTION") or "我有些触动"
        intensity = _parse_intensity(_extract_tag(raw, "INTENSITY"), default=0.45)
        chapter = _extract_tag(raw, "CHAPTER")
        return StoryBeat(
            text=narrative,
            emotion_label=emotion,
            emotion_intensity=intensity,
            chapter_hint=chapter,
        )

    def collapse_experiences(self, lines: list[str]) -> str:
        """将多段体验折成一段故事观一致的叙述（无 LLM 时简单拼接）。"""
        parts = [line.strip() for line in lines if line and line.strip()]
        if not parts:
            return ""
        if self._llm is None:
            joined = "；".join(parts[:6])
            return f"在同一时刻里，这些经历交织在一起：{joined}"[:280]
        prompt = (
            f"【故事观】\n{self._worldview.render()}\n\n"
            "以下体验片段在相近时刻发生，请合并为一段第一人称经历（100~220字）：\n"
            + "\n".join(f"- {p}" for p in parts)
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        ).strip()
        return _extract_tag(raw, "NARRATIVE") or raw

    def _build_prompt(self, brief: NarrativeBrief) -> str:
        dice = brief.dice_tendency.strip()
        dice_section = f"\n【命运基调】\n{dice}" if dice else ""
        return (
            f"【故事观】\n{self._worldview.render()}\n\n"
            f"【主体状态】\n{brief.profile_narrative.strip() or '（暂无）'}\n\n"
            f"【相关记忆】\n{_format_memories(brief.memory_lines)}\n\n"
            f"【本拍线索】\n{brief.hint.strip()}"
            f"{dice_section}\n\n"
            "写出一拍第一人称叙事："
        )

    def _fallback_beat(self, brief: NarrativeBrief) -> StoryBeat:
        hint = brief.hint.strip() or "片刻安静"
        text = (
            f"在《{self._worldview.title}》里，{self._worldview.protagonist}"
            f"停留在{hint}——空气里有细小的变动，我知道这一刻会被记住。"
        )
        return StoryBeat(
            text=text[:240],
            emotion_label="平静里有一点期待",
            emotion_intensity=0.42,
            chapter_hint=hint[:12],
        )
