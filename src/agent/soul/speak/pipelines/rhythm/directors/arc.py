from __future__ import annotations

from collections.abc import Callable

from ..contracts import ShareItem
from ..state import RhythmSessionState
from .json_util import extract_json_object
from .prompts import ARC_INIT_SYSTEM

DirectorGenerateFn = Callable[[str, str], str]


def arc_brief(
    state: RhythmSessionState,
    *,
    reason: str = "",
    share_queue: tuple[ShareItem, ...] = (),
    working_memory: str = "",
) -> str:
    lines = [
        "# 会话材料（供拟定对话弧）",
        f"session={state.session_id}",
    ]
    if reason.strip():
        lines.extend(["", "## 初始化原因", reason.strip()])
    if state.review.ready:
        lines.extend(
            [
                "",
                "## 上一场伪学习复盘（错开会话；只迁习惯）",
                "说明：以下来自另一场已结束的交互，不是本场前情。",
                "定弧时只吸收 abstract 习惯；summary 仅作背景，勿复用其剧情物件。",
            ]
        )
        if state.review.abstract.strip():
            lines.extend(["### 可迁移原则 abstract", state.review.abstract.strip()])
        if state.review.summary.strip():
            lines.extend(
                ["### 上一场 summary（勿当本场剧情）", state.review.summary.strip()]
            )
    lines.extend(
        [
            "",
            "## 情感",
            f"{state.affect.label}（{state.affect.valence}）",
            "",
            "## 待分享",
        ]
    )
    if not share_queue:
        lines.append("（空）")
    else:
        for idx, item in enumerate(share_queue[:5], start=1):
            lines.append(f"{idx}. {item.one_line()}")
    lines.extend(["", "## 最近对白"])
    history = state.recent_history(6)
    if not history:
        lines.append("（尚无对白）")
    else:
        for beat in history:
            lines.append(f"- {beat.one_line()}")
    if working_memory.strip():
        lines.extend(["", "## 工作记忆", working_memory.strip()[:400]])
    return "\n".join(lines)


class ArcDirector:
    name = "rhythm.arc"

    def __init__(self, generate_json: DirectorGenerateFn) -> None:
        self._generate_json = generate_json

    def init_arc(
        self,
        state: RhythmSessionState,
        *,
        reason: str = "cold_init",
        share_queue: tuple[ShareItem, ...] = (),
        working_memory: str = "",
    ) -> str:
        raw = self._generate_json(
            ARC_INIT_SYSTEM,
            arc_brief(
                state,
                reason=reason,
                share_queue=share_queue,
                working_memory=working_memory,
            ),
        )
        payload = extract_json_object(raw, director=self.name)
        text = str(
            payload.get("arc") or payload.get("text") or payload.get("snapshot") or ""
        ).strip()
        if not text:
            raise ValueError("rhythm.arc: empty arc text")
        state.set_arc(text)
        return text
