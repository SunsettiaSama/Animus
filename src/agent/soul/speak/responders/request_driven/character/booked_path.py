from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agent.soul.speak.responders.request_driven.directors.base import (
    DirectorLLMCaller,
    extract_json_object,
)

BookedAction = Literal["silence", "speak"]

_BOOKED_SYSTEM = (
    "你是角色本人。这是之前预约到点后的唤醒，不是用户刚发来的消息。"
    "两个选项：silence（继续沉默）或 speak（现在开口）。"
    "不要再次预约、延迟或安排下一次开口时间。"
    "先写清楚：你在做什么、心情如何、选哪个。不要写台词。"
    "输出文风保持客观、冷静、朴实。不用修辞，不抒情，不说教。\n"
    "输出 JSON："
    '{"doing":"…","mood":"…","action":"silence|speak",'
    '"reason":"一两句理由","flush_body":"短动作"}'
)


@dataclass(frozen=True)
class BookedTurnDecision:
    doing: str = ""
    mood: str = ""
    action: BookedAction = "speak"
    reason: str = ""
    flush_body: str = ""
    raw: str = ""

    @property
    def will_speak(self) -> bool:
        return self.action == "speak"

    @property
    def flush_text(self) -> str:
        speak_flag = "要开口" if self.action == "speak" else "先不开口"
        return (
            f"<speak>（{speak_flag}：{self.reason.strip() or '先按自己的节奏来。'}）</speak>"
        )


def _normalize_booked_action(raw: Any) -> BookedAction:
    text = str(raw or "").strip().lower()
    if text in (
        "silence",
        "silent",
        "hold",
        "delay",
        "book",
        "稍后",
        "预约",
        "沉默",
        "不开口",
    ):
        return "silence"
    if text in ("speak", "reply", "true", "1", "yes", "开口", "回复"):
        return "speak"
    if isinstance(raw, bool):
        return "speak" if raw else "silence"
    return "speak"


def decide_booked_turn(
    llm: DirectorLLMCaller | Any,
    *,
    session_id: str,
    turn_index: int = 0,
    origin: str = "booked",
    plot_intent: str = "",
    rhythm_enrichment: str = "",
    interaction_record: str = "",
    director_cue: str = "",
) -> BookedTurnDecision:
    """预约到点专用：只能沉默或回复，不能再预约。不走热路径决策。"""
    lines = [
        f"origin={origin}",
        f"turn_index={turn_index}",
        "本拍是预约到点唤醒；只能沉默或现在开口。",
    ]
    if director_cue.strip():
        lines.append(f"唤醒说明：{director_cue.strip()[:240]}")
    if plot_intent.strip():
        lines.append(f"本拍剧情：{plot_intent.strip()[:200]}")
    if rhythm_enrichment.strip():
        lines.append("导演用「你」给你的扩充：")
        lines.append(rhythm_enrichment.strip()[:600])
    if interaction_record.strip():
        lines.append("往来账本：")
        lines.append(interaction_record.strip()[:800])
    raw = ""
    if llm is not None and getattr(llm, "available", True):
        raw = str(
            llm.generate_json(
                system=_BOOKED_SYSTEM,
                user="\n".join(lines),
                session_id=session_id,
                director="character_booked_decision",
                turn_index=turn_index,
            )
            or ""
        )
    payload = extract_json_object(raw) if raw else {}
    if not payload:
        return BookedTurnDecision(
            doing=plot_intent[:120],
            mood="",
            action="speak",
            reason="预约到点，先接一下场",
            flush_body="你抬眼看了看通信设备",
            raw=raw,
        )
    action = _normalize_booked_action(payload.get("action", payload.get("will_speak")))
    return BookedTurnDecision(
        doing=str(payload.get("doing") or "").strip()[:160],
        mood=str(payload.get("mood") or "").strip()[:120],
        action=action,
        reason=str(payload.get("reason") or "").strip()[:200],
        flush_body=str(payload.get("flush_body") or "").strip()[:160],
        raw=raw,
    )