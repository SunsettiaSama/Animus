from __future__ import annotations

from collections.abc import Callable

from ..contracts import RhythmReview, ShareItem
from ..state import RhythmSessionState
from .json_util import extract_json_object
from .prompts import REVIEW_SYSTEM

DirectorGenerateFn = Callable[[str, str], str]


def review_brief(
    state: RhythmSessionState,
    *,
    share_queue: tuple[ShareItem, ...] = (),
) -> str:
    lines = [
        "# 本轮交互材料（供伪学习复盘）",
        f"session={state.session_id} beats={state.beat_index}",
        "",
        "## 本轮对话弧",
        state.arc_text.strip() or "（无）",
        "",
        "## 情感末态",
        f"{state.affect.label}（{state.affect.valence}）",
        "",
        "## 对白曲线（按时间）",
    ]
    history = state.recent_history(24)
    if not history:
        lines.append("（尚无对白）")
    else:
        for beat in history:
            lines.append(f"- {beat.one_line(limit=160)}")
    lines.extend(["", "## 导演轨迹（含 listen/hold，便于看是否僵住）"])
    directors = state.recent_directors(24)
    if not directors:
        lines.append("（无）")
    else:
        for beat in directors:
            lines.append(f"- {beat.one_line(limit=160)}")
    lines.extend(["", "## 待分享剩余"])
    if not share_queue:
        lines.append("（空）")
    else:
        for idx, item in enumerate(share_queue[:5], start=1):
            lines.append(f"{idx}. {item.one_line()}")
    return "\n".join(lines)


class ReviewDirector:
    name = "rhythm.review"

    def __init__(self, generate_json: DirectorGenerateFn) -> None:
        self._generate_json = generate_json

    def build_review(
        self,
        state: RhythmSessionState,
        *,
        share_queue: tuple[ShareItem, ...] = (),
    ) -> RhythmReview:
        raw = self._generate_json(
            REVIEW_SYSTEM,
            review_brief(state, share_queue=share_queue),
        )
        review = RhythmReview.from_payload(
            extract_json_object(raw, director=self.name)
        )
        if not review.abstract.strip():
            raise ValueError("rhythm.review: empty abstract")
        if not review.summary.strip():
            raise ValueError("rhythm.review: empty summary")
        state.set_review(review)
        return review
