from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM

from ...fsm.expectation.intent import parse_dialogue_expectation, split_refresh_payload
from ...fsm.state import PresenceState
from ..expectation import Expectation
from .block import DialogueBlock, DialogueSessionTracker, is_user_agent_dialogue
from config.soul.presence.config import DIALOGUE_FSM_REFRESH_EVERY_K
from .experience import DialogueExperience, render_dialogue_experience
from .result import DialogueObserveResult, DialogueRefreshResult

_REFRESH_SYSTEM = """\
你是 Agent 的「会话当下态」自叙系统。根据最近若干轮与用户的对话，用第一人称更新四维度自叙，每段 1-3 句，语气内省、具体。

字段说明：
- affect：此刻情感与心境（随对话推进后的感受）
- somatic：身体与精力感受
- thinking：正在浮现的思维或念头
- perception：对对话氛围与对方状态的感知
- dialogue_expectation：是否还需要用户进一步回复 none|optional|required|clarify|deferred

注意：working_memory 由 experience/dialogue 层维护（verbatim 截断），此处不生成。

严格输出合法 JSON，不含其它文字。"""

_REFRESH_SCHEMA = """\
{
  "affect": "我…",
  "somatic": "我…",
  "thinking": "我…",
  "perception": "我…",
  "dialogue_expectation": "none"
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"DialogueFsmRefresh: LLM 输出中未找到合法 JSON：{raw[:300]}")


def _format_blocks(blocks: list[DialogueBlock]) -> str:
    lines: list[str] = []
    for index, block in enumerate(blocks, start=1):
        lines.append(f"【块 {index}】")
        if block.user_text.strip():
            lines.append(f"用户：{block.user_text.strip()}")
        if block.agent_text.strip():
            lines.append(f"我：{block.agent_text.strip()}")
        if block.perception.strip():
            lines.append(f"感知：{block.perception.strip()}")
        if block.prior_thought.strip():
            lines.append(f"先前念头：{block.prior_thought.strip()}")
        if block.narration.strip():
            lines.append(f"叙述：{block.narration.strip()}")
    return "\n".join(lines)


def _fallback_narratives(blocks: list[DialogueBlock], state: PresenceState) -> dict[str, str]:
    last = blocks[-1] if blocks else None
    perception = ""
    thinking = ""
    if last is not None:
        perception = last.perception.strip() or last.user_text.strip() or state.perception.narrative
        thinking = last.narration.strip() or last.agent_text.strip() or state.cognition.thinking
    else:
        perception = state.perception.narrative
        thinking = state.cognition.thinking
    return {
        "affect": state.affect.narrative or "对话仍在继续，情绪随对方话语轻轻摆动。",
        "somatic": state.somatic.narrative or "身体保持交谈时的轻微专注。",
        "thinking": thinking,
        "perception": perception,
    }


def apply_dialogue_narratives(
    state: PresenceState,
    narratives: dict[str, str],
    *,
    preserve_working_memory: bool = False,
) -> None:
    preserved_wm = state.cognition.working_memory
    state.affect.narrative = narratives.get("affect", "")
    state.somatic.narrative = narratives.get("somatic", "")
    state.cognition.thinking = narratives.get("thinking", "")
    state.perception.narrative = narratives.get("perception", "")
    if preserve_working_memory:
        state.cognition.working_memory = preserved_wm
    else:
        state.cognition.working_memory = narratives.get("working_memory", "")


class DialogueFsmRefresher:
    """调用外部 agent（LLM）根据近期对话块刷新 FSM 四维度自叙。"""

    def __init__(self, llm: BaseLLM | None = None) -> None:
        self._llm = llm

    def generate(
        self,
        *,
        state: PresenceState,
        blocks: list[DialogueBlock],
    ) -> dict[str, str]:
        if not blocks:
            return _fallback_narratives([], state)
        if self._llm is None:
            return _fallback_narratives(blocks, state)

        current = state.render().strip() or "（尚无自叙）"
        transcript = _format_blocks(blocks)
        user = (
            f"当前自叙：\n{current}\n\n"
            f"最近 {len(blocks)} 个对话块：\n{transcript}\n\n"
            f"请按此 schema 输出：\n{_REFRESH_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [
                SystemMessage(content=_REFRESH_SYSTEM),
                HumanMessage(content=user),
            ]
        )
        data = _extract_json(raw)
        return {
            "affect": str(data.get("affect", "")).strip(),
            "somatic": str(data.get("somatic", "")).strip(),
            "thinking": str(data.get("thinking", "")).strip(),
            "perception": str(data.get("perception", "")).strip(),
            "dialogue_expectation": str(data.get("dialogue_expectation", "")).strip(),
        }

    def refresh(
        self,
        state: PresenceState,
        *,
        session_id: str,
        blocks: list[DialogueBlock],
    ) -> DialogueRefreshResult:
        raw = self.generate(state=state, blocks=blocks)
        narratives, meta = split_refresh_payload(raw)
        if not any(narratives.values()):
            narratives = _fallback_narratives(blocks, state)
            source = "fallback"
        else:
            source = "llm" if self._llm is not None else "fallback"
        apply_dialogue_narratives(state, narratives, preserve_working_memory=True)
        parsed_expectation = parse_dialogue_expectation(meta)
        return DialogueRefreshResult(
            session_id=session_id,
            applied=True,
            source=source,
            narratives=narratives,
            dialogue_expectation=parsed_expectation,
        )


@dataclass
class DialogueSessionTransition:
    """用户-agent 会话间状态转移：每 k 个对话块刷新 FSM。"""

    refresher: DialogueFsmRefresher = field(default_factory=DialogueFsmRefresher)
    interval: int = DIALOGUE_FSM_REFRESH_EVERY_K
    _trackers: dict[str, DialogueSessionTracker] = field(default_factory=dict)

    def block_count(self, session_id: str) -> int:
        tracker = self._trackers.get(session_id)
        if tracker is None:
            return 0
        return tracker.block_count

    def observe(
        self,
        state: PresenceState,
        block: DialogueBlock,
        *,
        session_id: str,
    ) -> DialogueObserveResult:
        if not is_user_agent_dialogue(block):
            return DialogueObserveResult(
                session_id=session_id,
                counted=False,
                notes=["dialogue: skipped non user-agent block"],
            )

        tracker = self._trackers.setdefault(session_id, DialogueSessionTracker())
        count = tracker.record(block)
        notes = [f"dialogue: block {count} recorded"]

        if count % self.interval != 0:
            return DialogueObserveResult(
                session_id=session_id,
                counted=True,
                block_count=count,
                refreshed=False,
                notes=notes,
            )

        recent = tracker.blocks[-self.interval :]
        refresh = self.refresher.refresh(state, session_id=session_id, blocks=recent)
        notes.append(f"dialogue: fsm refreshed after {count} blocks ({refresh.source})")
        return DialogueObserveResult(
            session_id=session_id,
            counted=True,
            block_count=count,
            refreshed=True,
            refresh=refresh,
            notes=notes,
        )

    def reset_session(self, session_id: str) -> None:
        self._trackers.pop(session_id, None)

    def finalize(
        self,
        state: PresenceState,
        *,
        session_id: str,
    ) -> DialogueExperience | None:
        """会话闭合：全量块刷新 FSM，导出连续体验并重置 tracker。"""
        tracker = self._trackers.pop(session_id, None)
        if tracker is None or not tracker.blocks:
            return None
        self.refresher.refresh(
            state,
            session_id=session_id,
            blocks=tracker.blocks,
        )
        return render_dialogue_experience(state, tracker.blocks)
