from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueCompressionBlock:
    """Speak 上下文压缩产出的一轮粗粒度体验块（跨边界 DTO）。"""

    session_id: str
    block_index: int
    summary: str
    emotion_label: str = ""
    valence: str = "neutral"
    salience: float = 0.5
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    transcript: str = ""
    interactor_id: str = ""


import json
import re
from dataclasses import dataclass as _dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.life.experience.domain.anchor_codec import (
    AnchorUnitContext,
    InteractionDirection,
    stamp_anchor_context,
)
from agent.soul.life.experience.domain.sources import ExperienceSource
from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)

from infra.llm import BaseLLM

_SYSTEM = """\
你是 Life 体验编写器。根据给定的多轮对话原文（工作记忆抛出），输出 Agent 主观体验字段 JSON。
忠实转述对话中已出现的事实与意图；emotion / valence / salience 反映 Agent 当下体验强度。
只输出 JSON，不要解释。"""

_SCHEMA_HINT = """\
{
  "perception": "对情境的感知描述（可引用对话事实，<=200字）",
  "narration": "恰好一句话事件叙述",
  "action_content": "Agent 在此段对话中的主要行为（<=80字）",
  "emotion_label": "命名情绪",
  "valence": "positive|negative|mixed|neutral",
  "salience": 0.5,
  "valence_delta": 0.0,
  "arousal_delta": 0.0,
  "salience_note": "显著性补充（可选，<=60字）"
}"""


@_dataclass(frozen=True)
class CompressionUnitResult:
    unit: ExperienceUnit
    raw_json: dict


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"体验编写未返回 JSON：{raw[:200]}")
    return json.loads(m.group())


def _clamp_salience(value: object) -> float:
    if value is None:
        return 0.5
    salience = float(value)
    return min(1.0, max(0.2, salience))


def build_unit_from_authoring(
    block: DialogueCompressionBlock,
    data: dict,
    *,
    interactor_id: str = "",
) -> ExperienceUnit:
    transcript = block.transcript.strip()
    perception = str(data.get("perception", "")).strip() or transcript
    narration = str(data.get("narration", "")).strip() or block.summary.strip() or perception[:240]
    action_content = (
        str(data.get("action_content", "")).strip()
        or block.summary.strip()
        or narration[:120]
    )
    salience_note = str(data.get("salience_note", "")).strip()
    if not salience_note:
        salience_note = block.summary.strip()

    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id=block.session_id,
            turn_index=block.block_index + 1,
            perception=perception,
            narration=narration,
            prior_thought=f"wm_flush:{block.block_index}",
        ),
        action=ExperienceAction(
            kind=ExperienceActionKind.speaking,
            content=action_content,
        ),
        feeling=ExperienceFeeling(
            salience=_clamp_salience(data.get("salience", block.salience)),
            emotion_label=str(data.get("emotion_label", block.emotion_label)).strip(),
            valence_delta=float(data.get("valence_delta", block.valence_delta) or 0.0),
            arousal_delta=float(data.get("arousal_delta", block.arousal_delta) or 0.0),
            salience_note=salience_note,
        ),
        source=ExperienceSource.interaction.value,
    )
    actor = (interactor_id or block.interactor_id).strip()
    stamp_anchor_context(
        unit,
        AnchorUnitContext(
            direction=InteractionDirection.inbound,
            session_id=block.session_id,
            interactor_id=actor,
        ),
    )
    return unit


def create_unit_from_compression(
    llm: BaseLLM,
    block: DialogueCompressionBlock,
    *,
    interactor_id: str = "",
    agent_persona_narrative: str = "",
) -> CompressionUnitResult:
    """压缩块 → ExperienceUnit（落图前的体验载体）。"""
    transcript = block.transcript.strip()
    if not transcript:
        raise ValueError("工作记忆抛出缺少对话原文 transcript")

    persona = agent_persona_narrative.strip()
    system = _SYSTEM
    if persona:
        system = f"{system}\n\n【Agent 人格锚点（体验语气须与此一致）】\n{persona}"

    user_lines = [
        f"会话 id：{block.session_id}",
        f"块序号：{block.block_index}",
        f"待编写体验的最近对话原文：\n{transcript}",
    ]
    if block.summary.strip():
        user_lines.append(f"（参考）上下文蒸馏句：{block.summary.strip()}")
    user_lines.append(f"\n输出 schema：\n{_SCHEMA_HINT}")
    raw = llm.generate_messages(
        [SystemMessage(content=system), HumanMessage(content="\n".join(user_lines))]
    )
    data = _extract_json(raw)
    unit = build_unit_from_authoring(
        block,
        data,
        interactor_id=interactor_id,
    )
    return CompressionUnitResult(unit=unit, raw_json=data)
