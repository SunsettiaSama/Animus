from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM

from ...fsm.expectation.intent import (
    apply_non_dialogue_share_refresh,
    split_refresh_payload,
)
from ...fsm.state import PresenceState
from ..dialogue.refresh import apply_dialogue_narratives
from .event import IncidentKind, LifeIncident
from .result import IncidentIngestResult, IncidentRefreshResult
from agent.soul.presence.transition.interaction import PresenceInteraction

_INCIDENT_SYSTEM = """\
你是 Agent 的「生活当下态」自叙系统。生活中发生了一件事（地标计划、地标兑现或意外），\
请用第一人称更新四维度自叙，表达 Agent 对这件事的看法与体感，每段 1-3 句，语气内省、具体。

字段说明：
- affect：对这件事的情感反应
- somatic：身体与精力感受
- working_memory：这件事在心里留下了什么
- thinking：正在浮现的念头或评价
- perception：对处境与环境的感知
- wants_to_share：是否想把这件事告诉用户（true/false）
- share_topic：若想分享，用一句话说想分享什么（否则空字符串）
- share_desire：分享意愿强度 none|mild|moderate|eager

严格输出合法 JSON，不含其它文字。"""

_INCIDENT_SCHEMA = """\
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

_KIND_LABELS: dict[IncidentKind, str] = {
    IncidentKind.landmark_planned: "地标计划（写入）",
    IncidentKind.landmark_filled: "地标兑现（完成）",
    IncidentKind.surprise: "意外事件",
}


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"IncidentFsmRefresh: LLM 输出中未找到合法 JSON：{raw[:300]}")


def _format_incident(incident: LifeIncident) -> str:
    lines = [
        f"类型：{_KIND_LABELS[incident.kind]}",
        f"要点：{incident.hint.strip()}",
        f"显著度：{incident.salience:.2f}",
    ]
    if incident.context.strip():
        lines.append(f"背景：{incident.context.strip()}")
    if incident.trigger.strip():
        lines.append(f"触发：{incident.trigger.strip()}")
    if incident.emotion_text.strip():
        lines.append(f"情绪线索：{incident.emotion_text.strip()}")
    return "\n".join(lines)


def _fallback_narratives(incident: LifeIncident, state: PresenceState) -> dict[str, str]:
    hint = incident.hint.strip()
    affect = state.affect.narrative
    if hint:
        if incident.kind == IncidentKind.surprise:
            affect = f"意外袭来：{hint}"
        elif incident.kind == IncidentKind.landmark_planned:
            affect = f"心里记下了一个打算：{hint}"
        else:
            affect = f"地标兑现后，我仍想着：{hint}"
    return {
        "affect": affect or "有某事在心里轻轻落位。",
        "somatic": state.somatic.narrative or "身体随事件微微绷紧又松开。",
        "working_memory": hint or state.cognition.working_memory,
        "thinking": state.cognition.thinking or f"我在回味「{hint}」意味着什么。",
        "perception": state.perception.narrative or "周围一切因这件事而略显不同。",
    }


class IncidentFsmRefresher:
    """调用外部 agent（LLM）根据 life 事件刷新 FSM 四维度自叙。"""

    def __init__(self, llm: BaseLLM | None = None) -> None:
        self._llm = llm

    def generate(
        self,
        *,
        state: PresenceState,
        incident: LifeIncident,
    ) -> dict[str, str]:
        if not incident.hint.strip():
            return _fallback_narratives(incident, state)
        if self._llm is None:
            return _fallback_narratives(incident, state)

        current = state.render().strip() or "（尚无自叙）"
        user = (
            f"当前自叙：\n{current}\n\n"
            f"刚发生的事件：\n{_format_incident(incident)}\n\n"
            f"请按此 schema 输出：\n{_INCIDENT_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [
                SystemMessage(content=_INCIDENT_SYSTEM),
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

    def refresh(
        self,
        state: PresenceState,
        incident: LifeIncident,
        *,
        session_id: str,
        interaction: PresenceInteraction | None = None,
    ) -> IncidentRefreshResult:
        if not incident.hint.strip():
            return IncidentRefreshResult(
                session_id=session_id,
                kind=incident.kind,
                applied=False,
                reason="empty hint",
            )
        raw = self.generate(state=state, incident=incident)
        narratives, meta = split_refresh_payload(raw)
        if not any(narratives.values()):
            narratives = _fallback_narratives(incident, state)
            source = "fallback"
        else:
            source = "llm" if self._llm is not None else "fallback"
        apply_dialogue_narratives(state, narratives)
        share_notes = apply_non_dialogue_share_refresh(
            state.expectation,
            interaction,
            meta,
            source=f"incident:{incident.kind.value}",
        )
        return IncidentRefreshResult(
            session_id=session_id,
            kind=incident.kind,
            applied=True,
            source=source,
            narratives=narratives,
            notes=share_notes,
        )


@dataclass
class IncidentTransition:
    """Life 事件注入 → FSM 看法更新。"""

    refresher: IncidentFsmRefresher = field(default_factory=IncidentFsmRefresher)

    def ingest(
        self,
        state: PresenceState,
        incident: LifeIncident,
        *,
        interaction: PresenceInteraction | None = None,
    ) -> IncidentIngestResult:
        if not incident.hint.strip():
            return IncidentIngestResult(
                session_id=incident.session_id,
                incident=incident,
                applied=False,
                notes=[f"incident: skipped empty {incident.kind.value}"],
            )
        refresh = self.refresher.refresh(
            state,
            incident,
            session_id=incident.session_id,
            interaction=interaction,
        )
        notes = [f"incident: {incident.kind.value} fsm refreshed ({refresh.source})"]
        notes.extend(refresh.notes)
        return IncidentIngestResult(
            session_id=incident.session_id,
            incident=incident,
            applied=refresh.applied,
            refresh=refresh,
            notes=notes,
        )
