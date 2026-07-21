from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..contracts import OnSceneFocus, OnSceneState
from ..state import RhythmSessionState
from .json_util import extract_json_object
from .prompts import ON_SCENE_SYSTEM

DirectorGenerateFn = Callable[[str, str], str]


def on_scene_brief(state: RhythmSessionState) -> str:
    lines = [
        "# 材料（供刷新临场状态）",
        f"session={state.session_id} beat={state.beat_index}",
        "",
        "## 情感",
        state.affect.label.strip() or "（未标）",
        "",
        "## 上一拍临场",
        state.on_scene.one_line() if state.on_scene.ready else "（尚无）",
        "",
        "## 最近对白（只看氛围，别抄成惦记清单）",
    ]
    history = state.recent_history(4)
    if not history:
        lines.append("（尚无对白）")
    else:
        for beat in history:
            lines.append(f"- {beat.one_line()}")
    return "\n".join(lines)


def _parse_focus(raw: object) -> OnSceneFocus:
    token = str(raw or "present").strip().lower()
    if token in ("drift", "absent", "away"):
        return "drift"
    if token in ("notice", "notice_other", "elsewhere"):
        return "notice"
    return "present"


def on_scene_from_payload(payload: dict[str, Any], *, beat_index: int) -> OnSceneState:
    text = str(payload.get("on_scene") or payload.get("text") or "").strip()
    if not text:
        raise ValueError("on_scene: empty text")
    return OnSceneState(
        text=text,
        focus=_parse_focus(payload.get("focus")),
        beat_index=beat_index,
    )


def should_refresh_on_scene(state: RhythmSessionState, *, every_k: int) -> bool:
    if every_k <= 0:
        return False
    if not state.on_scene.ready:
        return True
    return state.beats_since_on_scene >= every_k


class OnSceneDirector:
    """Synchronous on-scene refresh for v1; async slot reserved later."""

    name = "rhythm.on_scene"

    def __init__(self, generate_json: DirectorGenerateFn) -> None:
        self._generate_json = generate_json

    def refresh(self, state: RhythmSessionState) -> OnSceneState:
        raw = self._generate_json(ON_SCENE_SYSTEM, on_scene_brief(state))
        scene = on_scene_from_payload(
            extract_json_object(raw, director=self.name),
            beat_index=state.beat_index,
        )
        state.set_on_scene(scene)
        return scene

    def refresh_async(self, state: RhythmSessionState) -> None:
        """Reserved for presence/drive async pump; v1 stays synchronous."""
        del state
        raise NotImplementedError("rhythm.on_scene: async refresh not wired in v1")
