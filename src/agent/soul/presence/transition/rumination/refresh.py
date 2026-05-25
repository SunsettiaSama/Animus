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
from .event import RuminationSignal
from .result import RuminationIngestResult, RuminationRefreshResult
from agent.soul.presence.transition.interaction import PresenceInteraction

_RUMINATION_SYSTEM = """\
你是 Agent 的「记忆反刍当下态」自叙系统。一段旧记忆被重新浮现并反刍，\
请用第一人称更新四维度自叙，表达这段记忆此刻在心里留下的痕迹，每段 1-3 句，语气内省、具体。

字段说明：
- affect：反刍带来的情感与心境
- somatic：身体与精力感受
- working_memory：这段记忆在心里留下了什么
- thinking：正在浮现的念头或联想
- perception：对当下处境的感知（受记忆染色后）
- wants_to_share：是否想把这段反刍告诉用户（true/false）
- share_topic：若想分享，用一句话说想分享什么（否则空字符串）
- share_desire：分享意愿强度 none|mild|moderate|eager

严格输出合法 JSON，不含其它文字。"""

_RUMINATION_SCHEMA = """\
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
    raise ValueError(f"RuminationFsmRefresh: LLM 输出中未找到合法 JSON：{raw[:300]}")


def _format_rumination(rumination: RuminationSignal) -> str:
    lines = [f"反刍要点：{rumination.hint.strip() or '（无显式叙事，仅有记忆浮现）'}"]
    if rumination.emotion.strip():
        lines.append(f"主导情绪：{rumination.emotion.strip()}")
    if rumination.intensity > 0:
        lines.append(f"情绪强度：{rumination.intensity:.2f}")
    if rumination.wandered_ids:
        lines.append(f"浮现记忆：{', '.join(rumination.wandered_ids[:5])}")
    if rumination.ruminated_ids:
        lines.append(f"反刍记忆：{', '.join(rumination.ruminated_ids[:5])}")
    if rumination.tick_id.strip():
        lines.append(f"心跳：{rumination.tick_id.strip()}")
    if rumination.trigger.strip():
        lines.append(f"触发：{rumination.trigger.strip()}")
    return "\n".join(lines)


def _fallback_narratives(rumination: RuminationSignal, state: PresenceState) -> dict[str, str]:
    hint = rumination.hint.strip()
    emotion = rumination.emotion.strip()
    if hint:
        affect = f"某段记忆反刍上来：{hint}"
    elif emotion:
        affect = f"心里浮过一丝{emotion}，来自某段旧记忆。"
    else:
        affect = state.affect.narrative or "有某段记忆在心里轻轻翻页。"
    wm = hint or state.cognition.working_memory or "一段旧事仍在心里停留。"
    return {
        "affect": affect,
        "somatic": state.somatic.narrative or "身体随记忆的浮现微微一紧又松开。",
        "working_memory": wm,
        "thinking": state.cognition.thinking or (f"我在回味「{hint}」" if hint else "旧事的细节仍在拼凑。"),
        "perception": state.perception.narrative or "当下的一切因这段记忆而略显不同。",
    }


class RuminationFsmRefresher:
    """调用外部 agent（LLM）根据记忆反刍刷新 FSM 四维度自叙。"""

    def __init__(self, llm: BaseLLM | None = None) -> None:
        self._llm = llm

    def generate(
        self,
        *,
        state: PresenceState,
        rumination: RuminationSignal,
    ) -> dict[str, str]:
        if not rumination.hint.strip() and not rumination.ruminated_ids:
            return _fallback_narratives(rumination, state)
        if self._llm is None:
            return _fallback_narratives(rumination, state)

        current = state.render().strip() or "（尚无自叙）"
        user = (
            f"当前自叙：\n{current}\n\n"
            f"记忆反刍：\n{_format_rumination(rumination)}\n\n"
            f"请按此 schema 输出：\n{_RUMINATION_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [
                SystemMessage(content=_RUMINATION_SYSTEM),
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
        rumination: RuminationSignal,
        *,
        session_id: str,
        interaction: PresenceInteraction | None = None,
    ) -> RuminationRefreshResult:
        if not rumination.hint.strip() and not rumination.ruminated_ids:
            return RuminationRefreshResult(
                session_id=session_id,
                applied=False,
                reason="empty rumination",
            )
        raw = self.generate(state=state, rumination=rumination)
        narratives, meta = split_refresh_payload(raw)
        if not any(narratives.values()):
            narratives = _fallback_narratives(rumination, state)
            source = "fallback"
        else:
            source = "llm" if self._llm is not None else "fallback"
        apply_dialogue_narratives(state, narratives)
        share_notes = apply_non_dialogue_share_refresh(
            state.expectation,
            interaction,
            meta,
            source="rumination",
        )
        return RuminationRefreshResult(
            session_id=session_id,
            applied=True,
            source=source,
            narratives=narratives,
            notes=share_notes,
        )


@dataclass
class RuminationTransition:
    """记忆反刍注入 → FSM 当下态更新。"""

    refresher: RuminationFsmRefresher = field(default_factory=RuminationFsmRefresher)

    def ingest(
        self,
        state: PresenceState,
        rumination: RuminationSignal,
        *,
        interaction: PresenceInteraction | None = None,
    ) -> RuminationIngestResult:
        if not rumination.hint.strip() and not rumination.ruminated_ids:
            return RuminationIngestResult(
                session_id=rumination.session_id,
                rumination=rumination,
                applied=False,
                notes=["rumination: skipped empty payload"],
            )
        refresh = self.refresher.refresh(
            state,
            rumination,
            session_id=rumination.session_id,
            interaction=interaction,
        )
        notes = [f"rumination: fsm refreshed ({refresh.source})"]
        notes.extend(refresh.notes)
        return RuminationIngestResult(
            session_id=rumination.session_id,
            rumination=rumination,
            applied=refresh.applied,
            refresh=refresh,
            notes=notes,
        )
