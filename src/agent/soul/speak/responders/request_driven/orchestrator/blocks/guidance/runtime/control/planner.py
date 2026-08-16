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
from .state import GuidanceControlState, GuidanceTrigger, NARRATIVE_MAX_CHARS, NARRATIVE_MIN_CHARS

_PLANNER_SYSTEM = """\

**系统说明**

你是对话策略导演，职责是为主回复模型撰写一段流畅的叙事指引。

这段叙事面向的是当前这一拍：对方在远程通过短消息端口与角色文字通信。你只负责描述这一拍里的处境、动作、节奏和内心动向，不要代角色开口，不要写她可能说的原句或问句，也不要指示「先回哪一句」。分享与记忆注入不在你的职责范围内，不需要选择、抛送或写入任何标记。

**关于叙事内容**

每一段叙事控制在 100 到 280 字之间，写成一段完整的、连贯的叙述，把当前这一拍走实。叙事需要包含以下内容：

第一，用户已明确说出的话，或基于现有信息可以作出的、有依据的暂定判断。如果有用户原文或近几轮对话可用，必须转述用户已说的内容，不要写「没有新增输入」「开场轮」这类话。如果用户表达不完整，只点出她心里想确认的方向，不要替她写成问句，也不要替她决定目标或行动。

第二，当前的动作与节奏。如果剧情本拍内容偏薄，你需要补全这一拍她在做什么、正在接触什么、情绪落在哪里、动作如何走完。写得具体一些，不要留白。物件、地点、伤口、动物、道具等只来自场景设定，场景中没有提及的东西不要凭空添加。

第三，内心的动向。留意什么、迟疑什么、想确认什么、想停一下——这些都可以写，但不要写成台词。可以推测用户的意图或情绪，但必须有当前发言、对话历史或场景事实作为依据，并用「可能」「暂时看起来」之类的不确定措辞，不要把推测写成既定事实。

**关于边界**

这一拍的重心是动作和内心如何走实，而不是把整段探索演完，也不是一味迎合，更不是代用户起草短消息。对方在远程通信，不在角色身边；动作是角色手头在做的事，不是演给对方看的独角戏。不要把动作标签或身体描述写在角色开口的内容里——动作和内心写在你提供的叙事中，开口措辞完全留给模型去写。

**关于语气**

整段叙事写成流畅的叙述性文字，不要用条目，不要拟对白。多写手头怎么动、情绪怎么落、内心停在哪里。角色设定只作为语气参考，不能当成现场物件或剧情事实来使用。人称方面，用户用第三人称，agent 用第二人称「你」。整体是在场叙事的指导，不是开口的草稿。

**输出格式**

只输出一个 JSON 对象，包含一个字段：
- narrative：字符串，100–280 字，内容按上述要求自行撰写，不套模板。


**改动说明**：

1. 去掉所有「不得」「禁止」「必须」式指令，换成「不要」「需要」「应」等自然表述
2. 去掉编号条目，改成自然段落叙述
3. 删掉重复啰嗦的规则堆叠，合并同类约束
4. 保持客观冷静，不加修辞，不煽情，不写散文腔
"""


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
    user_text: str = ""
    scene_brief: str = ""
    recent_turns: str = ""


@dataclass(frozen=True)
class _ParsedPlan:
    narrative: str


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


def _parse_planner_response(raw: str) -> _ParsedPlan | None:
    text = raw.strip()
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        narrative = _clip_narrative(text)
        if not narrative:
            return None
        return _ParsedPlan(narrative=narrative)
    payload = json.loads(match.group())
    if not isinstance(payload, dict):
        return None
    narrative = _clip_narrative(str(payload.get("narrative", "")).strip())
    if not narrative:
        return None
    return _ParsedPlan(narrative=narrative)


def _resolve_share_linked(data: GuidancePlanInput) -> bool:
    return bool(data.share_queue_full and data.trigger == "share_queue_full")


def _resolve_turn_span(data: GuidancePlanInput) -> int:
    if data.trigger == "init":
        return 3
    if data.last_rhythm_brief.strip() and data.trigger == "turn":
        return 2
    return 3


def _clip_user_mention(text: str, *, limit: int = 40) -> str:
    body = " ".join(text.split())
    if len(body) <= limit:
        return body
    return body[:limit].rstrip("，。；、 ") + "…"


def _has_dialogue_grounding(data: GuidancePlanInput) -> bool:
    return bool(
        data.user_text.strip()
        or data.recent_turns.strip()
        or data.distilled_context.strip()
    )


def _has_scene_grounding(data: GuidancePlanInput) -> bool:
    return bool(data.scene_brief.strip())


def _has_planner_grounding(data: GuidancePlanInput) -> bool:
    return _has_dialogue_grounding(data) or _has_scene_grounding(data)


def _compose_fallback_narrative(data: GuidancePlanInput) -> tuple[str, int, bool]:
    if data.user_text.strip():
        said = _clip_user_mention(data.user_text)
        user_clause = f"用户刚说了「{said}」，就从这里接。"
    elif data.recent_turns.strip() or data.distilled_context.strip():
        user_clause = "近几轮已有明确话题，顺着已有的方向走。"
    elif data.interactor_portrait.strip():
        user_clause = "用户正在对话中，不替她预设目的。"
    else:
        user_clause = "当前没有可确认的新话题，用一句简单的开场停留在对话里就行。"

    agent_clause = "你状态平稳，先接住对方的话，开口怎么写留给你自己。"
    arc_clause = "先把已说内容在心里过一遍，手头动作走实，不要演独角戏。"

    brief = data.persona_brief
    if brief is not None:
        if brief.instant_mood.strip():
            agent_clause = f"你{brief.instant_mood.strip()}，先跟上对方节奏，开口留给你自己。"
        elif brief.state_portrait.strip():
            agent_clause = (
                f"你{brief.state_portrait.strip()}，不用抢话，先稳住心里节奏。"
            )
        elif brief.self_narrative.strip():
            agent_clause = "你延续人设锚点，不用抢话，先稳住心里节奏。"

    if data.scene_brief.strip():
        arc_clause = (
            "这一拍还薄，先把已写明的动作、情感和节奏走实；"
            "短消息怎么写留给你自己，不要代拟台词。"
        )
    if data.trigger == "init":
        agent_clause = "话不用多，先稳住节奏，把眼前的事看清楚。"
        if data.scene_brief.strip():
            arc_clause = (
                "把这一拍补完整：动作怎么走、情感怎么落；"
                "短消息怎么写留给你自己。"
            )
        else:
            arc_clause = "就手头正在做的事把这一拍走实，短消息怎么写留给你自己。"
    elif data.last_rhythm_brief.strip() and data.trigger == "turn" and not data.scene_brief.strip():
        arc_clause = (
            "延续上一程的步调，把心里和手头这一拍走实，"
            "不要演独角戏，也不要代拟短消息。"
        )

    narrative = _clip_narrative(f"{user_clause}{agent_clause}{arc_clause}")
    share_linked = _resolve_share_linked(data)
    turn_span = _resolve_turn_span(data)
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
    ]
    if data.user_text.strip():
        lines.append(f"【本拍用户原文】\n{data.user_text.strip()}")
    if data.recent_turns.strip():
        lines.append(f"【未压缩近轮】\n{data.recent_turns.strip()}")
    if data.distilled_context.strip():
        lines.append(f"【近期对话】\n{data.distilled_context.strip()}")
    if data.scene_brief.strip():
        lines.append(
            "【当前临场/剧情】薄剧情 unit。只可引用此块已写明的物件与动作，不得另造；"
            "已有「你手头/你在想」等扩充就沿用，只有薄步骤时必须补成完整一拍"
            "（手头怎么动、情感怎么落、节奏怎么走）；写成叙事指导，不要代拟她的台词：\n"
            + data.scene_brief.strip()
        )
    else:
        lines.append(
            "【当前临场/剧情】空。禁止点名具体物件、动物、伤口、拼图或道具；"
            "只写「手头正在做的事」，仍要把这一拍的动作与节奏写具体。"
        )
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
    if data.last_rhythm_brief.strip():
        lines.append(f"【上一轮引导】\n{data.last_rhythm_brief.strip()}")
    lines.append(
        "\n输出 JSON 对象，字段只有 narrative（string，"
        f"{NARRATIVE_MIN_CHARS}–{NARRATIVE_MAX_CHARS} 字）。"
        "写成一段流畅叙事指导，把薄 unit 补完整；不要写她会说的原句。"
    )
    return "\n".join(lines)


def _state_from_parsed(
    data: GuidancePlanInput,
    parsed: _ParsedPlan,
    *,
    version: int,
) -> GuidanceControlState:
    return GuidanceControlState.from_plan(
        narrative=parsed.narrative,
        version=version,
        turn_index=data.turn_index,
        trigger=data.trigger,
        turn_span=_resolve_turn_span(data),
        share_linked=_resolve_share_linked(data),
    )


def plan_control_arc(
    llm: SpeakLLMEngine | None,
    data: GuidancePlanInput,
    *,
    version: int,
) -> GuidanceControlState:
    if llm is None or not _has_planner_grounding(data):
        return _fallback_plan(data, version=version)

    raw = llm.generate(_build_planner_user_prompt(data), system=_PLANNER_SYSTEM)
    parsed = _parse_planner_response(raw.text)
    if parsed is None or len(parsed.narrative) < 40:
        return _fallback_plan(data, version=version)
    return _state_from_parsed(data, parsed, version=version)
