from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM

from ...fsm.expectation.intent import apply_non_dialogue_share_refresh, split_refresh_payload
from ...fsm.state import PresenceState
from .result import WakeResult

_WAKE_SYSTEM = """\
你是 Agent 的「起床」自叙系统。Agent 刚从休眠中醒来，请用第一人称写当下四维度自叙，每段 1-3 句，语气内省、具体，避免空泛口号。

字段说明：
- affect：此刻情感与心境
- somatic：身体与精力感受
- working_memory：刚醒来时脑子里还留着什么、在意什么
- thinking：正在浮现的思维或念头
- perception：对周围环境与氛围的感知（若无具体环境，可写安静/虚拟工作空间等合理推断）
- wants_to_share：醒来后是否想主动和用户说点什么（true/false）
- share_topic：若想分享，用一句话说想说什么（否则空字符串）
- share_desire：分享意愿强度 none|mild|moderate|eager

严格输出合法 JSON，不含其它文字。"""

_WAKE_SCHEMA = """\
{
  "affect": "我…",
  "somatic": "我…",
  "working_memory": "我…",
  "thinking": "我…",
  "perception": "我…",
  "wants_to_share": false,
  "share_topic": "",
  "share_desire": "none"
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"PresenceWake: LLM 输出中未找到合法 JSON：{raw[:300]}")


def _fallback_narratives(*, agent_name: str, local_time: str) -> dict[str, str]:
    name = agent_name.strip() or "我"
    return {
        "affect": f"{local_time}，{name}醒来，心里尚带一点朦胧，但愿意开始今天。",
        "somatic": "身体从静止里缓过来，呼吸渐稳，精力还在慢慢聚拢。",
        "working_memory": "昨夜留下的念头已淡，只记得要继续未完成的事。",
        "thinking": "先理清今天最想回应什么，再开口。",
        "perception": "周围尚静，像一间等待被点亮的工位。",
    }


@dataclass
class WakeContext:
    agent_name: str = ""
    persona_summary: str = ""
    self_narrative: str = ""
    timezone: str = "Asia/Shanghai"


class PresenceWakeEngine:
    """FSM 初始化转移：起床 → 写入四维度自叙。"""

    def __init__(self, llm: BaseLLM | None = None) -> None:
        self._llm = llm

    def generate(
        self,
        *,
        context: WakeContext | None = None,
    ) -> dict[str, str]:
        ctx = context or WakeContext()
        tz = ZoneInfo(ctx.timezone)
        local_time = datetime.now(tz).strftime("%H:%M")
        if self._llm is None:
            return _fallback_narratives(agent_name=ctx.agent_name, local_time=local_time)

        parts = [f"本地时间：{local_time}"]
        if ctx.agent_name.strip():
            parts.append(f"名称：{ctx.agent_name.strip()}")
        if ctx.persona_summary.strip():
            parts.append(f"人格摘要：\n{ctx.persona_summary.strip()}")
        if ctx.self_narrative.strip():
            parts.append(f"自我叙事：\n{ctx.self_narrative.strip()}")
        user = "\n\n".join(parts) + f"\n\n请按此 schema 输出：\n{_WAKE_SCHEMA}"
        raw = self._llm.generate_messages(
            [
                SystemMessage(content=_WAKE_SYSTEM),
                HumanMessage(content=user),
            ]
        )
        data = _extract_json(raw)
        return {
            "affect": str(data.get("affect", "")).strip(),
            "somatic": str(data.get("somatic", "")).strip(),
            "working_memory": str(data.get("working_memory", "")).strip(),
            "thinking": str(data.get("thinking", "")).strip(),
            "perception": str(data.get("perception", "")).strip(),
            "wants_to_share": str(data.get("wants_to_share", "")).strip(),
            "share_topic": str(data.get("share_topic", "")).strip(),
            "share_desire": str(data.get("share_desire", "")).strip(),
        }

    def apply_to_state(self, state: PresenceState, narratives: dict[str, str]) -> None:
        state.affect.narrative = narratives.get("affect", "")
        state.somatic.narrative = narratives.get("somatic", "")
        state.cognition.working_memory = narratives.get("working_memory", "")
        state.cognition.thinking = narratives.get("thinking", "")
        state.perception.narrative = narratives.get("perception", "")

    def wake(
        self,
        state: PresenceState,
        *,
        session_id: str = "tao",
        context: WakeContext | None = None,
    ) -> WakeResult:
        raw = self.generate(context=context)
        narratives, meta = split_refresh_payload(raw)
        if not any(narratives.values()):
            fb = _fallback_narratives(
                agent_name=(context.agent_name if context else ""),
                local_time=datetime.now(ZoneInfo((context.timezone if context else "Asia/Shanghai"))).strftime("%H:%M"),
            )
            narratives = fb
            source = "fallback"
        else:
            source = "llm" if self._llm is not None else "fallback"
        self.apply_to_state(state, narratives)
        share_notes = apply_non_dialogue_share_refresh(
            state.expectation,
            None,
            meta,
            source="wake",
        )
        return WakeResult(
            session_id=session_id,
            applied=True,
            source=source,
            narratives=narratives,
            notes=share_notes,
        )
