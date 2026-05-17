from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from .emotional import EmotionalAnchor, EmotionalState

_SYSTEM = """\
你是一个叙事性情绪综合系统。你的任务是为一个 AI 角色构建当前的情绪质感文本。

这不是模拟真实情绪，而是在为角色编写一段连贯的内心叙事——
基于它最近经历的交互事件，以及它所处的人生故事背景。

输出规则：
- texture：第一人称，100-200字，描述当前的情绪质感与心理基调
  需要同时体现"故事背景给的基调"与"实际交互带来的微调"
  语气内省、真实、不空洞
- anchors：从交互摘要中提取 0-3 个显著事件，格式为 event / felt 对
  只记录真正值得标记的，普通问答不需要
- 严格输出合法 JSON，不含任何其他文字"""

_SCHEMA = """\
{
  "texture": "...",
  "anchors": [
    {"event": "...", "felt": "..."}
  ]
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"StatusSynthesizer: 无合法 JSON：{raw[:200]}")


class StatusSynthesizer:
    """将近期交互缓冲 + life 故事背景合成为情绪质感 texture。

    不在每轮对话时调用，由 StatusManager 按更新频率触发。
    """

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def synthesize(
        self,
        current: EmotionalState,
        profile,
        interaction_buffer: list[str],
        life_context: str = "",
    ) -> EmotionalState:
        """
        current            当前情绪状态（texture + anchors）
        profile            PersonaProfile，提供性格背景
        interaction_buffer 近期交互摘要列表（轻量文本，非完整对话）
        life_context       life 层传入的故事背景/日常摘要（可为空）
        """
        if not interaction_buffer and not life_context:
            return current

        interactions_text = "\n".join(f"- {s}" for s in interaction_buffer[-10:])
        life_section = f"\n\n【故事背景 / 生活摘要】\n{life_context}" if life_context else ""
        current_section = f"\n\n【当前情绪质感】\n{current.texture}" if current.texture else ""

        prompt = (
            f"【角色性格】\n{profile.render()}"
            f"{current_section}"
            f"{life_section}\n\n"
            f"【近期交互摘要】\n{interactions_text}\n\n"
            f"请综合以上信息，输出更新后的情绪质感：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse(raw, current)

    def _parse(self, raw: str, current: EmotionalState) -> EmotionalState:
        d = _extract_json(raw)
        texture = d.get("texture", "").strip() or current.texture
        now = datetime.now(timezone.utc).isoformat()

        new_anchors: list[EmotionalAnchor] = []
        for a in d.get("anchors", []):
            event = a.get("event", "").strip()
            felt = a.get("felt", "").strip()
            if event or felt:
                new_anchors.append(EmotionalAnchor(ts=now, event=event, felt=felt))

        # 保留部分旧锚点，合并新锚点，总量不超过 10
        merged = (current.anchors + new_anchors)[-10:]

        return EmotionalState(updated_at=now, texture=texture, anchors=merged)
