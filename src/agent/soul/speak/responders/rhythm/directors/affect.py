from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..state import RhythmSessionState
from .json_util import extract_json_object
from .prompts import AFFECT_SYSTEM

DirectorGenerateFn = Callable[[str, str], str]


def affect_brief(state: RhythmSessionState, *, user_text: str, trigger: str) -> str:
    lines = [
        "# 材料（供修正情感）",
        (
            f"session={state.session_id} trigger={trigger} "
            f"beat={state.beat_index}"
        ),
        "",
        "## 当前情感",
        (
            f"label={state.affect.label} valence={state.affect.valence} "
            f"intensity={state.affect.intensity:.2f}"
        ),
        "",
        "## 本拍输入",
        user_text.strip() or "（主动/空闲，无用户新话）",
        "",
        "## 最近对白",
    ]
    history = state.recent_history(8)
    if not history:
        lines.append("（尚无对白）")
    else:
        for beat in history:
            lines.append(f"- {beat.one_line(limit=120)}")
    lines.extend(["", "## 最近导演轨迹"])
    directors = state.recent_directors(6)
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


def should_refresh_affect(state: RhythmSessionState, *, every_k: int) -> bool:
    if every_k <= 0:
        return False
    return state.beats_since_affect >= every_k


class AffectDirector:
    name = "rhythm.affect"

    def __init__(self, generate_json: DirectorGenerateFn) -> None:
        self._generate_json = generate_json

    def refresh(
        self,
        state: RhythmSessionState,
        *,
        user_text: str,
        trigger: str,
    ) -> tuple[str, str, float]:
        raw = self._generate_json(
            AFFECT_SYSTEM,
            affect_brief(state, user_text=user_text, trigger=trigger),
        )
        label, valence, intensity = affect_from_payload(
            extract_json_object(raw, director=self.name)
        )
        state.set_affect(label=label, valence=valence, intensity=intensity)
        state.mark_affect_refreshed()
        return label, valence, intensity
