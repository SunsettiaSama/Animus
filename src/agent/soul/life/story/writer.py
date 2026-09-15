"""life.story.writer — life 侧编剧：把预约轴上的地标演绎写成可演材料。

职责（导演/编剧归 life，R6）：
- 输入是已经"发生"在生活里的材料——``fill_landmark`` 提前演化出的完整情节
  （或重启/失效后从手账读回的 ``Landmark.narrative``）；
- 输出是给角色的"想说的话"（BeatDraft），**必须说明白什么时间发生了什么
  事情，并和前情串起来**（时间明确叙事）；
- 确定性整形兜底，``llm_compose`` 缝留予后续接 LLM 润色（失败即回兜底）。

叙事整形不是可有无：角色开口说的第一句就要让用户听懂"几点、发生了什么、
接着上文哪件事"——这是时间轴呈现（前端）的内容地基。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from agent.soul.storybus import BeatDraft, BeatProvenance, PerformanceHint

logger = logging.getLogger(__name__)

_FRESH_SEC = 6 * 3600


def _parse_ts(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw or "").strip())
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def hhmm(raw: str) -> str:
    """ISO 时刻 → 本地 HH:MM（解析失败返回空串）。"""
    dt = _parse_ts(raw)
    if dt is None:
        return ""
    return dt.astimezone().strftime("%H:%M")


def _valid_until(from_raw: str) -> str:
    dt = _parse_ts(from_raw) or datetime.now(timezone.utc)
    return datetime.fromtimestamp(dt.timestamp() + _FRESH_SEC, tz=timezone.utc).isoformat()


class LandmarkScreenwriter:
    """地标预约轴的编剧：演化材料 → 时间明确、前情串联的 beat 草稿。"""

    def __init__(
        self,
        *,
        llm_compose: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        self._llm_compose = llm_compose

    # ── 演化材料 → beat 草稿 ───────────────────────────────────────────────

    def write_landmark_beat(
        self,
        fill: dict[str, Any],
        *,
        prev: list[dict[str, Any]] | None = None,
    ) -> BeatDraft | None:
        """提前演化的填充结果 → beat 草稿（deliver_at 之前仅入预跑池）。"""
        narrative = str(fill.get("hint") or fill.get("narrative") or "").strip()
        landmark_id = str(fill.get("landmark_id") or "").strip()
        scheduled_at = str(fill.get("scheduled_at") or "").strip()
        if not narrative or not landmark_id:
            return None
        text = self._compose(
            narrative,
            when=scheduled_at,
            intention=str(fill.get("intention") or "").strip(),
            prev=prev or [],
        )
        return BeatDraft(
            narrative=text,
            channels=tuple(fill.get("channels") or ()),
            kind="agenda_due",
            hint=PerformanceHint(
                urgency="normal",
                share_desire=min(0.95, 0.5 + float(fill.get("salience", 0.6) or 0.6) * 0.4),
                valid_until=_valid_until(scheduled_at or None),
            ),
            provenance=BeatProvenance(
                landmark_id=landmark_id,
                agenda_id=str(fill.get("landmark_agenda_id") or ""),
                source_tick=scheduled_at,   # 剧情时间随 beat 走（演出落账用）
            ),
            cached=True,
            beat_id=f"beat-lm-{landmark_id}",   # 确定性幂等键：跨路径生产天然去重
        )

    def write_landmark_echo(self, landmark: dict[str, Any]) -> BeatDraft | None:
        """已演化但未开口的地标（重启恢复/失效重估）→ beat 草稿。

        材料取手账里持久化的 ``narrative``，零 LLM；确定性 beat_id 保证与
        到点触发路径、重投路径互斥，不会对同一地标开两次口。
        """
        return self.write_landmark_beat(landmark)

    def outline_for(self, fill: dict[str, Any]) -> str:
        """剧情卡片大纲段（冻结）：预约时刻 + 意图。"""
        when = hhmm(str(fill.get("scheduled_at") or ""))
        intention = str(fill.get("intention") or "一段生活").strip()
        return f"「今日 {when}」{intention}" if when else intention

    # ── 叙事整形 ───────────────────────────────────────────────────────────

    def _compose(
        self,
        narrative: str,
        *,
        when: str,
        intention: str,
        prev: list[dict[str, Any]],
    ) -> str:
        if self._llm_compose is not None:
            try:
                text = self._llm_compose({
                    "narrative": narrative,
                    "when": when,
                    "intention": intention,
                    "prev": list(prev),
                })
                text = str(text or "").strip()
                if text:
                    return text
            except Exception:  # noqa: BLE001 — LLM 润色失败回确定性兜底
                logger.exception("[story.writer] llm_compose failed; fallback")
        return self._compose_deterministic(narrative, when=when, prev=prev)

    @staticmethod
    def _compose_deterministic(
        narrative: str,
        *,
        when: str,
        prev: list[dict[str, Any]],
    ) -> str:
        """确定性整形：说明白几点 + 接着前情哪件事。"""
        stamp = hhmm(when)
        link = ""
        for item in reversed(prev):
            prev_text = str(item.get("text") or item.get("narrative") or "").strip()
            if not prev_text:
                continue
            prev_at = hhmm(str(item.get("occurred_at") or item.get("at") or ""))
            link = f"接着{prev_at}那件事，" if prev_at else "接着刚才那件事，"
            break
        if stamp and link:
            return f"{stamp}了。{link}{narrative}"
        if stamp:
            return f"{stamp}了。{narrative}"
        if link:
            return f"{link}{narrative}"
        return narrative
