from __future__ import annotations

from typing import Any

from ...contracts import TextGenerator
from ...stage import StageState
from ..base import extract_json_object, generate_text

AFFECT_SYSTEM = (
    "你在做 agent 的情感修正：根据最近对白、导演轨迹和本拍输入，"
    "重估当前情绪底色。\n"
    "这是供后续节奏/拼接阅读的状态，不是角色台词，也不决定 gate。\n"
    "\n"
    "只输出 JSON：\n"
    '{"label":"短口语情绪标签",'
    '"valence":"positive|neutral|negative|mixed",'
    '"intensity":0.0,'
    '"reason":"一句话说明"}\n'
    "\n"
    "要求：\n"
    "- label 写当前底色，避免每次复读同一个贴纸。\n"
    "- 只根据本场材料修正，不继承上一场具体剧情。\n"
    "- intensity 是轻量体感，不参与门控；别用阈值口吻。\n"
)


def affect_brief(stage: StageState, *, user_text: str, trigger: str) -> str:
    lines = [
        "# 材料（供修正情感）",
        f"session={stage.session_id} trigger={trigger} turn={stage.turn_index} poll={stage.poll_index}",
        "",
        "## 当前情感",
        f"label={stage.affect.label} valence={stage.affect.valence} intensity={stage.affect.intensity:.2f}",
        "",
        "## 本拍输入",
        user_text.strip() or "（空闲轮询，无用户新话）",
        "",
        "## 最近对白",
    ]
    beats = stage.recent_beats(8)
    if not beats:
        lines.append("（尚无对白）")
    else:
        for beat in beats:
            lines.append(f"- {beat.one_line(limit=120)}")
    lines.extend(["", "## 最近导演轨迹"])
    directors = stage.recent_directors(6)
    if not directors:
        lines.append("（无）")
    else:
        for beat in directors:
            lines.append(f"- {beat.one_line(limit=120)}")
    return "\n".join(lines)


def _parse_valence(raw: object) -> str:
    text = str(raw or "neutral").strip().lower()
    if text in ("positive", "negative", "mixed", "neutral"):
        return text
    return "neutral"


def affect_from_payload(payload: dict[str, Any]) -> tuple[str, str, float]:
    label = str(payload.get("label") or payload.get("affect") or "").strip()
    if not label:
        raise ValueError("affect: empty label")
    valence = _parse_valence(payload.get("valence"))
    intensity = float(payload.get("intensity", 0.0) or 0.0)
    return label, valence, max(0.0, min(1.0, intensity))


def should_refresh_affect(stage: StageState, *, every_k: int) -> bool:
    if every_k <= 0:
        return False
    return stage.beats_since_affect >= every_k


def refresh_affect(
    llm: TextGenerator,
    stage: StageState,
    *,
    user_text: str,
    trigger: str,
) -> tuple[str, str, float]:
    raw = generate_text(
        llm,
        system=AFFECT_SYSTEM,
        user=affect_brief(stage, user_text=user_text, trigger=trigger),
    )
    label, valence, intensity = affect_from_payload(
        extract_json_object(raw, director="rhythm.affect")
    )
    stage.set_affect(label=label, valence=valence, intensity=intensity)
    stage.mark_affect_refreshed()
    return label, valence, intensity
