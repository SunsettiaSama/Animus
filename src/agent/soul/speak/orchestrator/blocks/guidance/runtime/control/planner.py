from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent.soul.speak.llm.engine import SpeakLLMEngine

from agent.soul.speak.orchestrator.blocks.guidance.runtime.inbound.persona_brief import (
    render_persona_planner_blocks,
)
from agent.soul.speak.orchestrator.blocks.persona import PersonaOutboundBrief

from .candidate_types import RecallPlannerCandidate, SharePlannerCandidate
from .consume import resolve_emit_recall_unit_id, resolve_emit_share_queue_index
from .state import GuidanceControlState, GuidanceTrigger, NARRATIVE_MAX_CHARS, NARRATIVE_MIN_CHARS

_PLANNER_SYSTEM = """\
你是对话引导撰写者，为扮演 agent 的主模型写「当下该怎么演」的内心导向。
这不是素材蒸馏：不要把候选逐条复述进 narrative，不要写成摘要清单。

【必写 · narrative】连贯自然段（100–200 字），融合：
1) 用户此刻状态或目的（「用户…」一句）；
2) agent 此刻状态与节奏（「你…」一句）；
3) 对话弧线（接下来怎么接，自然句收尾）。

【可选 · narrative 内标记】仅当本轮真的需要时，可在 narrative 内最多各一处：
- 「（分享：…）」须与 emit_share_index 一致（抛出时才写）；
- 「（回忆：…）」须与 emit_recall_index 一致（抛出时才写）。
有候选 ≠ 必须抛出；多数轮次 emit 应为 null。

【回忆 · 不必全叙述】「回忆候选」不是要写进正文的清单：
- social / event 各至多 1 条，由池内加权随机抽出（social 偏新、event 偏漫游）；上轮已入选的 unit 下轮权重降低但仍可能出现。
- 即使两条都在，也可以整条都不引用（emit_recall_index=null，且 narrative 不写「（回忆：…）」）。
- 禁止把候选逐条改写成摘要；只有情绪节拍真的需要时才 emit 一条。

【抛出索引 · 与 narrative 分列】输出 JSON（不要 markdown 代码块）：
{
  "narrative": "……正文……",
  "emit_share_index": null 或 分享候选中的 planner 下标（整数）,
  "emit_recall_index": null 或 回忆候选中的 planner 下标（整数）
}
规则：
- 仅当本轮打算把该条分享/回忆「交给后续 speak 回合消费」时，才填对应 index；否则 null。
- emit_share_index 只引用【分享候选】里列出的 [0],[1],…；emit_recall_index 只引用【回忆候选】。
- 填了 emit 就可以在 narrative 里轻点对应标记；不填 emit 则不要在 narrative 里写该标记。
- share_queue_full=true 时默认 emit_share_index=null，除非用户话题明显在等你说这件事。
- 禁止编造候选外事实；禁止在 narrative 里写 trigger、share_queue、JSON 字段名。

人称：用户第三人称，agent 第二人称「你」。
"""

_EXAMPLE_NEUTRAL = (
    "用户可能在等你先开口，但还没想好怎么说。"
    "你状态平稳，不必抢话，先短句接住对方的节奏。"
    "接下来你打算跟着对方的引子走，由浅入深，不一次说满。"
)

_EXAMPLE_JSON = (
    '{"narrative": "'
    + _EXAMPLE_NEUTRAL
    + '", "emit_share_index": null, "emit_recall_index": null}'
)


@dataclass(frozen=True)
class GuidancePlanInput:
    session_id: str
    turn_index: int
    distilled_context: str
    persona_portrait: str
    interactor_portrait: str
    share_preview: str
    recall_preview: str
    persona_brief: PersonaOutboundBrief | None = None
    share_candidates: tuple[SharePlannerCandidate, ...] = ()
    recall_candidates: tuple[RecallPlannerCandidate, ...] = ()
    last_rhythm_brief: str = ""
    share_queue_count: int = 0
    share_queue_full: bool = False
    trigger: GuidanceTrigger = "turn"


@dataclass(frozen=True)
class _ParsedPlan:
    narrative: str
    emit_share_index: int | None
    emit_recall_index: int | None


def _strip_wrapper(text: str) -> str:
    normalized = text.strip()
    normalized = re.sub(r"^【对话引导】\s*", "", normalized)
    normalized = normalized.strip().strip('"').strip('"').strip("'")
    normalized = normalized.strip().strip("【").strip("】")
    return " ".join(normalized.split())


def _clip_narrative(text: str) -> str:
    body = _strip_wrapper(text)
    if len(body) <= NARRATIVE_MAX_CHARS:
        return body
    return body[:NARRATIVE_MAX_CHARS].rstrip("，。；、")


def _parse_optional_index(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "null":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _parse_planner_response(raw: str) -> _ParsedPlan | None:
    text = raw.strip()
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        narrative = _clip_narrative(text)
        if not narrative:
            return None
        return _ParsedPlan(narrative=narrative, emit_share_index=None, emit_recall_index=None)
    payload = json.loads(match.group())
    if not isinstance(payload, dict):
        return None
    narrative = _clip_narrative(str(payload.get("narrative", "")).strip())
    if not narrative:
        return None
    return _ParsedPlan(
        narrative=narrative,
        emit_share_index=_parse_optional_index(payload.get("emit_share_index")),
        emit_recall_index=_parse_optional_index(payload.get("emit_recall_index")),
    )


def _narrative_has_share(narrative: str) -> bool:
    return "（分享：" in narrative


def _resolve_share_linked(
    data: GuidancePlanInput,
    narrative: str,
    *,
    emit_share_queue_index: int | None,
) -> bool:
    if emit_share_queue_index is not None:
        return True
    if _narrative_has_share(narrative):
        return True
    if data.share_queue_full and data.trigger == "share_queue_full":
        return True
    return False


def _resolve_turn_span(data: GuidancePlanInput, *, share_linked: bool) -> int:
    if share_linked and (data.share_queue_full or data.share_queue_count > 0):
        return 4
    if data.trigger == "init":
        return 3
    if data.last_rhythm_brief.strip() and data.trigger == "turn":
        return 2
    return 3


def _compose_fallback_narrative(data: GuidancePlanInput) -> tuple[str, int, bool]:
    if data.distilled_context.strip():
        user_clause = "用户方才的话里似乎还有未说透的意思，可能在等你先读懂再回应。"
    elif data.interactor_portrait.strip():
        user_clause = "用户此刻在和你说话，真实目的未必已经完全摊开。"
    else:
        user_clause = "用户还在对话里，意图不算明朗，需要你边听边判断。"

    agent_clause = "此时你状态平稳，不必抢话，先短句接住对方的节奏。"
    arc_clause = "接下来你打算跟着对方的引子走，由浅入深，不一次说满。"
    brief = data.persona_brief
    if brief is not None:
        if brief.instant_mood.strip():
            agent_clause = f"此时{brief.instant_mood.strip()}，先短句接住对方的节奏。"
        elif brief.state_portrait.strip():
            agent_clause = (
                f"此时你{brief.state_portrait.strip()}，不必抢话，先稳住节奏。"
            )
        elif brief.self_narrative.strip():
            agent_clause = "此时你延续既定人设锚点，不必抢话，先短句接住对方的节奏。"

    if data.share_queue_full:
        agent_clause = (
            "此时你心里有话想说，却不宜在这一轮说透，"
            "先接住对方，不必展开细节。"
        )
        arc_clause = (
            "接下来你打算优先响应当下对白，若对方问起再考虑是否轻点一句引子，"
            "不要抢主导，也不要编造细节。"
        )
    elif data.share_preview.strip() and data.share_queue_count > 0:
        agent_clause = "此时你隐约有点想分享的冲动，但还不必在这一轮说透。"
        arc_clause = "接下来你打算先听清对方，再视气氛决定是否轻轻带一句。"

    if data.trigger == "init":
        agent_clause = "此时你话不需要多，先稳住节奏，像平时那样听清再开口。"
        arc_clause = "接下来你打算自然接话，让用户引领，你再顺势加深。"
    elif data.last_rhythm_brief.strip() and data.trigger == "turn":
        arc_clause = (
            "接下来你打算延续上一程对话的步调，短句承接，"
            "在对方引导下继续把话接下去。"
        )

    narrative = _clip_narrative(f"{user_clause}{agent_clause}{arc_clause}")
    share_linked = _resolve_share_linked(data, narrative, emit_share_queue_index=None)
    turn_span = _resolve_turn_span(data, share_linked=share_linked)
    return narrative, turn_span, share_linked


def _fallback_plan(data: GuidancePlanInput, *, version: int) -> GuidanceControlState:
    narrative, turn_span, share_linked = _compose_fallback_narrative(data)
    return GuidanceControlState.from_plan(
        narrative=narrative,
        version=version,
        turn_index=data.turn_index,
        trigger=data.trigger,
        turn_span=turn_span,
        share_linked=share_linked,
    )


def _build_planner_user_prompt(data: GuidancePlanInput) -> str:
    lines = [
        "【编排信号 · 勿写入 narrative】",
        f"trigger={data.trigger}",
        f"share_queue_count={data.share_queue_count}",
        f"share_queue_full={data.share_queue_full}",
        f"\nJSON 格式示例（emit 均为 null）：\n{_EXAMPLE_JSON}",
    ]
    if data.distilled_context.strip():
        lines.append(f"【近期对话】\n{data.distilled_context.strip()}")
    persona_blocks = (
        render_persona_planner_blocks(data.persona_brief)
        if data.persona_brief is not None
        else []
    )
    if persona_blocks:
        lines.extend(persona_blocks)
    elif data.persona_portrait.strip():
        lines.append(f"【agent 人设·自叙】\n{data.persona_portrait.strip()}")
    if data.interactor_portrait.strip():
        lines.append(f"【对话者画像】\n{data.interactor_portrait.strip()}")
    if data.share_preview.strip():
        lines.append(f"【分享候选】\n{data.share_preview.strip()}")
    if data.recall_preview.strip():
        lines.append(f"【回忆候选】\n{data.recall_preview.strip()}")
    if data.last_rhythm_brief.strip():
        lines.append(f"【上一轮引导】\n{data.last_rhythm_brief.strip()}")
    lines.append(
        f"\n请输出 JSON，narrative 长度约 {NARRATIVE_MIN_CHARS}–{NARRATIVE_MAX_CHARS} 字。"
    )
    return "\n".join(lines)


def _state_from_parsed(
    data: GuidancePlanInput,
    parsed: _ParsedPlan,
    *,
    version: int,
) -> GuidanceControlState:
    emit_share_queue_index = resolve_emit_share_queue_index(
        parsed.emit_share_index,
        data.share_candidates,
    )
    emit_recall_unit_id = resolve_emit_recall_unit_id(
        parsed.emit_recall_index,
        data.recall_candidates,
    )
    share_linked = _resolve_share_linked(
        data,
        parsed.narrative,
        emit_share_queue_index=emit_share_queue_index,
    )
    turn_span = _resolve_turn_span(data, share_linked=share_linked)
    return GuidanceControlState.from_plan(
        narrative=parsed.narrative,
        version=version,
        turn_index=data.turn_index,
        trigger=data.trigger,
        turn_span=turn_span,
        share_linked=share_linked,
        emit_share_queue_index=emit_share_queue_index,
        emit_recall_unit_id=emit_recall_unit_id,
    )


def plan_control_arc(
    llm: SpeakLLMEngine | None,
    data: GuidancePlanInput,
    *,
    version: int,
) -> GuidanceControlState:
    if llm is None:
        return _fallback_plan(data, version=version)

    raw = llm.generate(_build_planner_user_prompt(data), system=_PLANNER_SYSTEM)
    parsed = _parse_planner_response(raw.text)
    if parsed is None or len(parsed.narrative) < 40:
        return _fallback_plan(data, version=version)
    return _state_from_parsed(data, parsed, version=version)
