from __future__ import annotations

from ..orchestrator.state.core.delivery import build_delivery_plan
from ..orchestrator.state.core.types import SessionSnapshot
from .agent import append_frame_prompt
from .base import (
    DIRECTOR_VOICE,
    DirectorLLMCaller,
    DirectorOutput,
    extract_json_object,
    parse_delivery_plan_payload,
)
from .fallback import fallback_director_output


class TurnDeliveryDirector:
    name = "turn_delivery"

    _SYSTEM = (
        f"{DIRECTOR_VOICE}\n"
        "你的职责：确定节奏——分几段、每段等多久、段与段之间如何衔接。\n"
        "frame 里的沉默日志、叙事舞台和临场事件，是你拟定下一拍语气和节奏的依据。"
        "用它们判断临场是否合拍，再给出分段等待。\n"
        "sample_narration 写这一拍的连续过程：手头的动作、情感、过渡、姿态。用「你」来指导角色。"
        "动作要写具体——物件、手势、光线、位置——不要留空。"
        "不写台词，不用「我」扮演角色，屏幕对面的人称作「对方」，对方不在现场。"
        "角色只发一条短消息，不要写成独角戏式的完整演进。\n"
        "segments[].text 用极短的占位符（推荐「…」）；最终正文由角色生成。\n"
        "continuity=finish：本轮编排收束，可以立刻让角色开口。"
        "continuity=append：还需要继续编排，暂不交接。\n"
        "wait_ms：第一段至少 120 毫秒，普通情况 200 到 2800 毫秒，情绪重的场景不超过 4200 毫秒。"
        "0 表示无需等待。\n"
        "输出文风保持客观、冷静、朴实。不用修辞，不抒情，不说教。\n"
        '输出 JSON：{"continuity":"append|finish","sample_narration":"",'
        '"segments":[{"text":"…","wait_ms":0,"wait_reason":"…","continuity":"finish"}]}'
    )

    def __init__(self, llm: DirectorLLMCaller) -> None:
        self._llm = llm

    def run(self, snapshot: SessionSnapshot, *, user_text: str = "") -> DirectorOutput:
        prompt = self._build_prompt(snapshot, user_text=user_text)
        raw = self._llm.generate_json(
            system=self._SYSTEM,
            user=prompt,
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        payload = extract_json_object(raw)
        if not payload:
            output = fallback_director_output(
                self.name,
                snapshot,
                user_text=user_text,
                raw=raw,
            )
            return output
        plan = parse_delivery_plan_payload(
            payload,
            turn_index=snapshot.signals.turn_index,
            plan_id=snapshot.snapshot_id,
        )
        return DirectorOutput(
            director=self.name,
            payload={"delivery_plan": plan.snapshot()},
            reason="delivery_ok",
        )

    def _build_prompt(self, snapshot: SessionSnapshot, *, user_text: str) -> str:
        lines = [
            f"turn_index={snapshot.signals.turn_index}",
            f"push_phase={snapshot.runtime.push_phase}",
            f"segment={snapshot.runtime.current_segment_index}/{snapshot.runtime.segment_total}",
            f"partial={snapshot.runtime.partial_output_preview[:300]}",
            f"intent={snapshot.orchestrator.director_decisions.get('user_intent', '')}",
        ]
        text = user_text.strip() or snapshot.dialogue.user_text.strip()
        if text:
            lines.append(f"user_text={text[:400]}")
        manager_brief = str(
            snapshot.orchestrator.compose_meta.get("compose_manager_director_brief") or ""
        ).strip()
        if manager_brief:
            lines.append(f"compose_manager={manager_brief[:400]}")
        elif snapshot.dialogue.working_memory.strip():
            lines.append(f"working_memory={snapshot.dialogue.working_memory.strip()[:400]}")
        memory_brief = str(
            snapshot.orchestrator.compose_meta.get("compose_manager_memory_brief") or ""
        ).strip()
        if memory_brief:
            lines.append(f"memory_brief={memory_brief[:240]}")
        return append_frame_prompt("\n".join(lines), snapshot)


def apply_turn_delivery_output(state, output: DirectorOutput, *, pending: bool = True) -> None:
    payload = output.payload.get("delivery_plan") or {}
    if not payload:
        return
    from ..orchestrator.state.core.delivery import ReplySegment
    from ..orchestrator.state.core.enums import normalize_continuity

    segments = []
    for item in payload.get("segments") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            ReplySegment(
                text=text,
                wait_ms=int(item.get("wait_ms", 0) or 0),
                wait_reason=str(item.get("wait_reason", "")).strip(),
                continuity=normalize_continuity(str(item.get("continuity", "finish"))),
            ),
        )
    plan = build_delivery_plan(
        segments=segments,
        continuity=str(payload.get("continuity", "finish")),
        sample_narration=str(payload.get("sample_narration", "")).strip(),
        plan_id=str(payload.get("plan_id", "")).strip(),
        turn_index=int(payload.get("turn_index", 0) or 0),
    )
    if pending:
        state.pending_delivery_plan = plan
    else:
        state.delivery_plan = plan
