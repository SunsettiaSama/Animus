from __future__ import annotations

from ..state.core.presence_card import CharacterPresenceCard
from ..state.core.types import SessionSnapshot
from .agent import append_frame_prompt
from .base import DirectorLLMCaller, DirectorOutput, extract_json_object


class PresenceCardDirector:
    """导演写入角色临场状态卡片（心情 + 简述），供注入角色上下文。"""

    name = "presence_card"

    _SYSTEM = (
        "你是临场状态导演。为角色写一张「临场状态卡片」，给角色本人读，不是台词。\n"
        "词条：\n"
        "- mood：当下心情（短词或短语）\n"
        "- brief：此刻状态简述（一两句口语）\n"
        "只输出 JSON："
        '{"mood":"…","brief":"…","reason":"…"}'
    )

    def __init__(self, llm: DirectorLLMCaller | None = None) -> None:
        self._llm = llm

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str = "",
        previous: CharacterPresenceCard | None = None,
        poll: bool = False,
    ) -> DirectorOutput:
        text = user_text.strip() or snapshot.dialogue.user_text.strip()
        prev = previous if previous is not None and previous.ready else None
        if self._llm is not None and self._llm.available:
            decided = self._decide_llm(
                snapshot,
                user_text=text,
                previous=prev,
                poll=poll,
            )
            if decided is not None:
                return DirectorOutput(
                    director=self.name,
                    payload=decided,
                    reason=str(decided.get("reason") or "director_llm"),
                )

        # 无 LLM：沿用旧卡或给轻量默认，避免空卡冲刷角色
        if prev is not None:
            return DirectorOutput(
                director=self.name,
                payload={
                    "mood": prev.mood,
                    "brief": prev.brief,
                    "extra": dict(prev.extra),
                    "reason": "keep_previous",
                    "poll": poll,
                },
                reason="keep_previous",
                used_fallback=True,
            )
        mood = "平静"
        brief = "留意着对话，尚未明显动情。"
        if text:
            brief = "刚接到用户话，正在感受气氛。"
        return DirectorOutput(
            director=self.name,
            payload={
                "mood": mood,
                "brief": brief,
                "reason": "heuristic_default",
                "poll": poll,
            },
            reason="heuristic_default",
            used_fallback=True,
        )

    def _decide_llm(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str,
        previous: CharacterPresenceCard | None,
        poll: bool,
    ) -> dict | None:
        phase = "poll" if poll else "ingress"
        prev_line = previous.one_line() if previous is not None else "（尚无）"
        lines = [
            f"阶段={phase}",
            f"turn={snapshot.signals.turn_index}",
            f"上一张临场卡={prev_line}",
            f"user_text={user_text[:280]}",
            f"context_distill={(snapshot.dialogue.context_distill or '')[:240]}",
            "要求：mood 短；brief 一两句；勿复述待分享清单；勿写成角色台词。",
        ]
        raw = self._llm.generate_json(
            system=self._SYSTEM,
            user=append_frame_prompt("\n".join(lines), snapshot),
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        data = extract_json_object(raw)
        if not data:
            return None
        mood = str(data.get("mood") or "").strip()
        brief = str(data.get("brief") or data.get("on_scene") or data.get("text") or "").strip()
        if not mood and not brief:
            return None
        extra_raw = data.get("extra") if isinstance(data.get("extra"), dict) else {}
        extra = {
            str(k).strip(): str(v).strip()
            for k, v in extra_raw.items()
            if str(k).strip() and str(v).strip()
        }
        return {
            "mood": mood or "平静",
            "brief": brief or "留意着当下。",
            "extra": extra,
            "reason": str(data.get("reason") or "director_llm"),
            "poll": poll,
        }


def apply_presence_card_output(
    state,
    output: DirectorOutput,
    *,
    turn_index: int = 0,
) -> CharacterPresenceCard | None:
    payload = dict(output.payload or {})
    payload["turn_index"] = turn_index or int(payload.get("turn_index") or 0)
    card = CharacterPresenceCard.from_dict(payload)
    if card is None:
        return None
    state.presence_card = card
    return card
