"""LLM writer for the memory_distill fallback chain."""

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.voice_rules import YOU_VOICE_RULES
from worker.state.memory_distill.bundle import PortraitSourceBundle
from worker.state.schema import MemoryPortraitState, utc_now_iso

_MAX_NARRATIVE_CHARS = 380

_SYSTEM = f"""\
你是主 Agent 记忆画像蒸馏器。根据给定的长期记忆条目与中期摘要，写一段供 Worker 执行期注入的「当前记忆画像」。

职责边界：
- 只写记忆中已出现的事实、主题、倾向与近期关注点；
- 不要重复静态身份名片、说话习惯或快变情绪（那是 Persona / Presence）；
- 不要编造未给出的事件。

{YOU_VOICE_RULES}

输出要求：
- 自然中文，200–380 字，一段话（最多两个自然段）
- 以「你最近记得 / 你持续关注」为主线
- 不要 JSON、不要 markdown、不要列表、不要字段标题

只输出正文。"""


def _clamp_chars(text: str, max_chars: int) -> str:
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _extract_plain_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.DOTALL)
    return text.strip().strip('"').strip("'").strip()


class MemoryPortraitWriter:
    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def distill(self, bundle: PortraitSourceBundle) -> MemoryPortraitState:
        if bundle.is_empty:
            return MemoryPortraitState.empty(source_revision=bundle.source_revision)

        human_parts: list[str] = []
        if bundle.stable_anchor:
            human_parts.append(
                "【稳定锚点（勿重复身份名片）】\n"
                + _clamp_chars(bundle.stable_anchor, 360)
            )
        if bundle.lines:
            numbered = "\n".join(
                f"{i}. {line}" for i, line in enumerate(bundle.lines, 1)
            )
            human_parts.append("【长期记忆条目】\n" + numbered)
        if bundle.worker_unit_lines:
            numbered_w = "\n".join(
                f"{i}. {line}" for i, line in enumerate(bundle.worker_unit_lines, 1)
            )
            human_parts.append("【本轮 Worker 单位轨迹摘要】\n" + numbered_w)
        if bundle.medium_text:
            human_parts.append("【中期摘要】\n" + bundle.medium_text)
        human_parts.append("请输出「你·当前记忆画像」连贯正文。")

        raw = self._llm.generate_messages(
            [
                SystemMessage(content=_SYSTEM),
                HumanMessage(content="\n\n".join(human_parts)),
            ]
        )
        narrative = _clamp_chars(_extract_plain_text(raw), _MAX_NARRATIVE_CHARS)
        if not narrative:
            raise ValueError("MemoryPortraitWriter: 蒸馏正文为空")
        return MemoryPortraitState(
            narrative=narrative,
            source_revision=bundle.source_revision,
            updated_at=utc_now_iso(),
            source_unit_ids=bundle.unit_ids,
            source_medium_chars=bundle.medium_chars,
        )
