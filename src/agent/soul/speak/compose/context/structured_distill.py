from __future__ import annotations

import json
import re

from agent.soul.memory.session.types import DialogueCompressionBlock
from agent.soul.speak.compose.context.chunk_types import DialogueContextChunk
from agent.soul.speak.llm.engine import SpeakLLMEngine

_STRUCTURED_SYSTEM = (
    "你是会话体验压缩器。"
    "根据给定的对话原文与此前压缩摘要，输出本轮体验的 JSON。"
    "忠实转述已出现的事实与意图；emotion / valence / salience 反映 Agent 主观体验强度。"
    "只输出 JSON，不要解释。"
)

_SCHEMA_HINT = """\
{
  "summary": "恰好一句话压缩摘要",
  "emotion_label": "命名情绪",
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
            lines.append(f"{index}. 我：{chunk.agent_text}")
    return "\n".join(lines)


def _fallback_block(
    session_id: str,
    block_index: int,
    batch: list[DialogueContextChunk],
    prior: list[str],
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
    )


def distill_compression_block(
    llm: SpeakLLMEngine | None,
    *,
    session_id: str,
    block_index: int,
    batch: list[DialogueContextChunk],
    prior: list[str],
) -> DialogueCompressionBlock:
    if llm is None:
        return _fallback_block(session_id, block_index, batch, prior)

    lines: list[str] = []
    if prior:
        lines.append("此前压缩摘要：")
        lines.extend(f"- {line}" for line in prior)
    lines.append(f"待压缩的最近 {len(batch)} 轮对话：")
    lines.append(_render_transcript(batch))
    lines.append(f"\n输出 schema：\n{_SCHEMA_HINT}")
    raw = llm.generate("\n".join(lines), system=_STRUCTURED_SYSTEM)
    data = _extract_json(raw.text)
    summary = str(data.get("summary", "")).strip()
    if not summary:
        return _fallback_block(session_id, block_index, batch, prior)
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
    )
