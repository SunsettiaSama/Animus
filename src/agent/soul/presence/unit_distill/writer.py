from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.voice_rules import YOU_VOICE_RULES
from infra.llm import BaseLLM

from ..state.lingering import RecentExperiencePortrait
from .prose import clamp_chars, validate_agent_prose

_SYSTEM = f"""\
你是 Presence 近期经历蒸馏器。根据给定的若干条生命体验单元，写一段给「扮演该角色的 LLM」看的近期状态说明。

职责边界：只写最近发生的事、你还在带着的时段情绪；不要重复 persona 里的说话习惯或身份名片；不要写当下对话瞬间的恼怒（那是 Speak 自管）。

{YOU_VOICE_RULES}

输出要求：
- 自然中文，200–350 字，一段话（最多两个自然段）
- 过去时为主，带时间线（今天/刚才/这两天…）
- 客观复述经历为主，把仍在持续的 mood 织进同一段，句末可少许你的感受
- 不要 JSON、不要 markdown、不要列表、不要「情感：」「事件：」等字段标题

只输出正文。"""


def _format_unit_for_prompt(unit: ExperienceUnit) -> str:
    mood = unit.feeling.effective_mood_span()
    subj = unit.feeling.effective_subjective_narrative()
    narration = unit.situation.narration.strip()
    parts = [f"- 时间 {unit.ts}", f"  来源 {unit.source or 'unknown'}"]
    if subj:
        parts.append(f"  感受 {subj}")
    elif narration:
        parts.append(f"  叙述 {narration}")
    if mood:
        parts.append(f"  时段情绪 {mood}")
    return "\n".join(parts)


class PresenceUnitDistillWriter:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def distill_batch(
        self,
        units: list[ExperienceUnit],
        *,
        max_chars: int = 350,
        persona_dialogue_hint: str = "",
    ) -> RecentExperiencePortrait:
        if not units:
            raise ValueError("PresenceUnitDistillWriter: units 为空")

        unit_blocks = "\n".join(_format_unit_for_prompt(u) for u in units)
        human_parts = [
            "【体验单元批次】",
            unit_blocks,
            "\n请输出「你·近期经历」连贯正文。",
        ]
        if persona_dialogue_hint.strip():
            human_parts.insert(
                0,
                f"【勿重复以下 persona 对话切片】\n{persona_dialogue_hint.strip()[:240]}",
            )

        raw = self._llm.generate_messages(
            [
                SystemMessage(content=_SYSTEM),
                HumanMessage(content="\n".join(human_parts)),
            ]
        )
        narrative = clamp_chars(validate_agent_prose(raw), max_chars)
        return RecentExperiencePortrait(
            narrative=narrative,
            distilled_at=datetime.now(timezone.utc).isoformat(),
            source_unit_ids=[u.id for u in units],
            last_distilled_unit_id=units[-1].id,
        )
