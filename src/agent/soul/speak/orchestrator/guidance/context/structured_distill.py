from __future__ import annotations

import json
import re

from agent.soul.memory.io.session import DialogueCompressionBlock
from agent.soul.voice_rules import YOU_VOICE_RULES
from agent.soul.speak.orchestrator.guidance.context.chunk_types import DialogueContextChunk
from agent.soul.speak.llm.engine import SpeakLLMEngine

def _structured_system(agent_persona_narrative: str = "") -> str:
    base = (
        "你是会话体验压缩器。"
        "根据给定的对话原文与此前压缩摘要，输出本轮体验的 JSON。\n"
        f"{YOU_VOICE_RULES}\n"
        "带明确时间锚（今天/刚才/这两天…）。"
        "忠实转述已出现的事实与意图；emotion / valence / salience 反映你当下的体验强度。"
        "只输出 JSON，不要解释。"
    )
    persona = agent_persona_narrative.strip()
    if not persona:
        return base
    return (
        f"{base}\n\n"
        f"【Agent 人格锚点（压缩语气须与此一致）】\n{persona}"
    )

_SCHEMA_HINT = """\
{
  "summary": "恰好一句话：你+时间+客观摘要，句末可少许你的感受",
  "emotion_label": "命名情绪（短标签）",
  "mood_span": "你+时段情绪，如「接下来两三天你会觉得有点沮丧」",
  "linger_days": 2.0,
  "subjective_narrative": "你+时间：可略多你的感受（<=120字），仍以事实线为骨",
  "valence": "positive|negative|mixed|neutral",
  "salience": 0.5,
  "valence_delta": 0.0,
  "arousal_delta": 0.0
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"压缩服务未返回 JSON：{raw[:200]}")
    return json.loads(m.group())


def _render_transcript(batch: list[DialogueContextChunk]) -> str:
    lines: list[str] = []
    for index, chunk in enumerate(batch, start=1):
        if chunk.user_text:
            lines.append(f"{index}. 用户：{chunk.user_text}")
        if chunk.agent_text:
            lines.append(f"{index}. 你：{chunk.agent_text}")
    return "\n".join(lines)


def _fallback_block(
    session_id: str,
    block_index: int,
    batch: list[DialogueContextChunk],
    prior: list[str],
    *,
    interactor_id: str = "",
) -> DialogueCompressionBlock:
    parts: list[str] = []
    if prior:
        parts.append(" ".join(prior[-2:]))
    for chunk in batch:
        if chunk.user_text:
            parts.append(chunk.user_text)
        if chunk.agent_text:
            parts.append(chunk.agent_text)
    summary = " ".join(parts).strip()[:240]
    return DialogueCompressionBlock(
        session_id=session_id,
        block_index=block_index,
        summary=summary or f"会话块 {block_index + 1}",
        transcript=_render_transcript(batch),
        salience=0.45,
        interactor_id=interactor_id,
    )


def distill_compression_block(
    llm: SpeakLLMEngine | None,
    *,
    session_id: str,
    block_index: int,
    batch: list[DialogueContextChunk],
    prior: list[str],
    agent_persona_narrative: str = "",
    interactor_id: str = "",
) -> DialogueCompressionBlock:
    if llm is None:
        return _fallback_block(
            session_id, block_index, batch, prior, interactor_id=interactor_id
        )

    lines: list[str] = []
    if prior:
        lines.append("此前压缩摘要：")
        lines.extend(f"- {line}" for line in prior)
    lines.append(f"待压缩的最近 {len(batch)} 轮对话：")
    lines.append(_render_transcript(batch))
    lines.append(f"\n输出 schema：\n{_SCHEMA_HINT}")
    raw = llm.generate("\n".join(lines), system=_structured_system(agent_persona_narrative))
    data = _extract_json(raw.text)
    summary = str(data.get("summary", "")).strip()
    if not summary:
        return _fallback_block(
            session_id, block_index, batch, prior, interactor_id=interactor_id
        )
    salience_raw = data.get("salience", 0.5)
    salience = float(salience_raw) if salience_raw is not None else 0.5
    salience = min(1.0, max(0.2, salience))
    valence_delta = float(data.get("valence_delta", 0.0) or 0.0)
    arousal_delta = float(data.get("arousal_delta", 0.0) or 0.0)
    return DialogueCompressionBlock(
        session_id=session_id,
        block_index=block_index,
        summary=summary,
        emotion_label=str(data.get("emotion_label", "")).strip(),
        valence=str(data.get("valence", "neutral")).strip().lower() or "neutral",
        salience=salience,
        valence_delta=valence_delta,
        arousal_delta=arousal_delta,
        transcript=_render_transcript(batch),
        interactor_id=interactor_id,
    )
