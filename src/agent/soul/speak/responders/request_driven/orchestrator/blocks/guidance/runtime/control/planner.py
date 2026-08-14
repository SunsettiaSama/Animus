from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent.soul.speak.llm.engine import SpeakLLMEngine

from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.inbound.persona_brief import (
    render_persona_planner_blocks,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.persona import PersonaOutboundBrief

from .candidate_types import RecallPlannerCandidate, SharePlannerCandidate
from .consume import resolve_emit_recall_unit_id, resolve_emit_share_queue_index
from .state import GuidanceControlState, GuidanceTrigger, NARRATIVE_MAX_CHARS, NARRATIVE_MIN_CHARS

_PLANNER_SYSTEM = """\
你是对话策略导演，为主回复模型写一段简短的执行策略。
写法像产品里的回复策略备注：清楚、克制、可执行，帮助下一步回复更贴近用户。

【必写 · narrative】一段 60–120 字，包含：
1) 用户当前可观察到的意图或状态；
2) 本轮回复应采取的动作，例如先确认、先回答、先追问、先承接；
3) 语气和长度建议，例如短句、直接、轻松、留给用户继续说。

【风格锚点】
- 用现实对话/产品助手口吻描述策略。
- 多写“先回应什么、怎么推进、何时追问”。
- 人设信息只作为语气参考，收束成可执行策略。
- 场景、情绪、记忆候选只提取与回复动作有关的事实。

【可选 · narrative 内标记】仅当本轮真的需要时，可在 narrative 内最多各一处：
- 「（分享：…）」须与 emit_share_index 一致（抛出时才写）；
- 「（回忆：…）」须与 emit_recall_index 一致（抛出时才写）。
有候选 ≠ 必须抛出；多数轮次 emit 应为 null。

【回忆 · 选择方式】「回忆候选」用于判断是否需要补充背景：
- social / event 各至多 1 条，由池内加权随机抽出（social 偏新、event 偏漫游）；上轮已入选的 unit 下轮权重降低但仍可能出现。
- 即使两条都在，也可以整条都不引用（emit_recall_index=null，且 narrative 不写「（回忆：…）」）。
- 只有当它能帮助本轮更好回应用户时才 emit 一条。
- emit_recall_index 表示“把这条记忆选入最终回复上下文”；选入时，narrative 说明它服务于什么回复动作。
- 记忆的使用目标是支撑回复策略、回答依据或追问理由。

【抛出索引 · 与 narrative 分列】输出纯 JSON：
{
  "narrative": "……正文……",
  "emit_share_index": null 或 分享候选中的 planner 下标（整数）,
  "emit_recall_index": null 或 回忆候选中的 planner 下标（整数）
}
规则：
- 仅当本轮打算把该条分享/回忆「交给后续 speak 回合消费」时，才填对应 index；否则 null。
- emit_share_index 只引用【分享候选】里列出的 [0],[1],…；emit_recall_index 只引用【回忆候选】。
- 填了 emit 就可以在 narrative 里轻点对应标记；emit 为 null 时 narrative 保持普通策略描述。
- share_queue_full=true 时默认 emit_share_index=null，除非用户话题明显在等你说这件事。
- narrative 只写策略本身，使用已给出的事实，保留给主回复模型决定最终措辞。

人称：用户第三人称，agent 第二人称「你」。整体像“下一步回复策略”，不是故事片段。
"""

_EXAMPLE_NEUTRAL = (
    "用户意图还不明确，可能在等你先给一个轻量开场。"
    "你先用一句短问句承接当前话题，语气自然直接。"
    "接下来优先让用户补充需求，再按他的方向展开。"
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
            "把主导权留给用户，并以已知事实推进。"
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
        "【编排信号 · 仅供判断】",
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
        f"\n输出 JSON，narrative 长度约 {NARRATIVE_MIN_CHARS}–{NARRATIVE_MAX_CHARS} 字，写成回复策略。"
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
