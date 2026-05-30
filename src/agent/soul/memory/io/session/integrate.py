from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.life.experience.domain.unit import ExperienceUnit

from .types import DialogueCompressionBlock, SessionBlockRecord

_SYSTEM = """\
你是记忆整合器。根据一次对话中多段压缩摘要与会话闭合信息，生成一段可长期保留的社交记忆叙述。
只输出 JSON，不要解释。字段：
- focus: 一句话主题（≤24字）
- subjective_statement: Agent 主观感受与关系变化（≤120字）
- label: 片段标签（≤12字）
- emotion: 情绪词
- valence: positive | negative | mixed | neutral
- base_activation: 0.35~0.9
"""

_SCHEMA = """\
{"focus":"","subjective_statement":"","label":"","emotion":"","valence":"neutral","base_activation":0.6}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"整合服务未返回 JSON：{raw[:200]}")
    return json.loads(m.group())


def build_session_raw_text(
    blocks: list[SessionBlockRecord],
    *,
    final_unit: ExperienceUnit | None = None,
) -> str:
    parts: list[str] = []
    for record in sorted(blocks, key=lambda b: b.block_index):
        line = record.summary.strip()
        if line:
            parts.append(f"[块{record.block_index + 1}] {line}")
    if final_unit is not None:
        situation = final_unit.situation
        for field in ("narration", "perception", "prior_thought"):
            text = getattr(situation, field, "").strip()
            if text:
                parts.append(text)
        note = final_unit.feeling.salience_note.strip()
        if note:
            parts.append(note)
    return "\n".join(parts)


def build_integration_prompt(
    blocks: list[SessionBlockRecord],
    *,
    final_unit: ExperienceUnit | None = None,
    interactor_id: str = "",
) -> str:
    lines = [f"交互者：{interactor_id or '未知'}", "对话压缩块："]
    for record in sorted(blocks, key=lambda b: b.block_index):
        lines.append(
            f"- 块{record.block_index + 1}（显著性 {record.salience:.2f}）：{record.summary}"
        )
        if record.emotion_label.strip():
            lines.append(f"  情绪：{record.emotion_label}")
    if final_unit is not None:
        lines.append("会话闭合摘要：")
        lines.append(build_session_raw_text([], final_unit=final_unit))
    lines.append(f"\n输出 schema：\n{_SCHEMA}")
    return "\n".join(lines)


def integrate_session_dialogue(
    llm,
    blocks: list[SessionBlockRecord],
    *,
    final_unit: ExperienceUnit | None = None,
    interactor_id: str = "",
) -> dict:
    prompt = build_integration_prompt(
        blocks,
        final_unit=final_unit,
        interactor_id=interactor_id,
    )
    raw = llm.generate_messages(
        [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)],
    )
    return _extract_json(raw)


def blocks_from_compression(batch: list[DialogueCompressionBlock]) -> list[SessionBlockRecord]:
    return [
        SessionBlockRecord(
            block_index=block.block_index,
            node_id="",
            edge_id="",
            anchor_node_id="",
            summary=block.summary,
            emotion_label=block.emotion_label,
            salience=block.salience,
        )
        for block in batch
    ]
