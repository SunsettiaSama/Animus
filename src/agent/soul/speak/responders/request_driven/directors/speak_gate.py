from __future__ import annotations

from ..orchestrator.state.core.types import SessionSnapshot
from .agent import append_frame_prompt
from .base import DIRECTOR_VOICE, DirectorLLMCaller, DirectorOutput, extract_json_object
from .fallback import fallback_speak_gate


class SpeakGateDirector:
    name = "speak_gate"

    _SYSTEM = (
        f"{DIRECTOR_VOICE}\n"
        "你的职责：开口门控——对照临场材料判断是否合拍，决定 listen、speak、hold 或 brew。\n"
        "参考 frame 里的内容：无用户输入元数据日志、用户舞台、临场事件、角色临场卡、命运骰。\n"
        "沉默日志是多个角度的观察记录；叙事舞台和临场事件是经过梳理的现场依据——"
        "用这些来判断下一拍的节奏。日志行数本身不代表必须开口。"
        "speak 是发一条短消息，不是演一场戏。"
        "用户未明说的意图由角色自己把握，台词由角色完成。\n"
        "输出文风保持客观、冷静、朴实。不用修辞，不抒情，不说教。\n"
        '输出 JSON：{"action":"listen|speak|hold|brew","reason":"…"}'
    )
    def __init__(self, llm: DirectorLLMCaller) -> None:
        self._llm = llm

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str = "",
        has_delivery_plan: bool = False,
    ) -> DirectorOutput:
        prompt = self._build_prompt(
            snapshot,
            user_text=user_text,
            has_delivery_plan=has_delivery_plan,
        )
        raw = self._llm.generate_json(
            system=self._SYSTEM,
            user=prompt,
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        payload = extract_json_object(raw)
        if not payload:
            gate = fallback_speak_gate(snapshot, has_plan=has_delivery_plan)
            return DirectorOutput(
                director=self.name,
                payload={"action": gate},
                reason="fallback_gate",
                used_fallback=True,
            )
        action = str(payload.get("action", "hold")).strip().lower()
        if action not in ("listen", "speak", "hold", "brew"):
            action = fallback_speak_gate(snapshot, has_plan=has_delivery_plan)
        return DirectorOutput(
            director=self.name,
            payload={
                "action": action,
                "reason": str(payload.get("reason", "")).strip(),
            },
            reason="gate_ok",
        )

    def _build_prompt(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str,
        has_delivery_plan: bool,
    ) -> str:
        lines = [
            f"typing_active={snapshot.runtime.typing_active}",
            f"typing_idle={snapshot.runtime.typing_idle}",
            f"push_phase={snapshot.runtime.push_phase}",
            f"has_delivery_plan={has_delivery_plan}",
            f"brew_queue_depth={snapshot.runtime.brew_queue_depth}",
            "请结合 frame 里的沉默观察与叙事临场，判断下一节奏是否符合预期。",
        ]
        if user_text.strip():
            lines.append(f"user_text={user_text.strip()[:200]}")
        return append_frame_prompt("\n".join(lines), snapshot)


def apply_speak_gate_output(state, output: DirectorOutput) -> None:
    state.speak_gate = str(output.payload.get("action", "hold")).strip() or "hold"
