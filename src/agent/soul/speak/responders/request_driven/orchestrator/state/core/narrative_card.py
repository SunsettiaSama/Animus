from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_SILENCE_LOG_MAX = 40

# 十条角度：时间元数据后的「未发言」表述，供叙事侧合理化；不硬编码单一句式。
SILENCE_OBSERVATION_PHRASES: tuple[str, ...] = (
    "现场暂无新的用户发言",
    "用户这一拍保持沉默",
    "用户或许正停顿思索，尚未开口",
    "对话空档仍在延续，用户未接话",
    "用户没有给出新的输入",
    "对面安静着，没有听见回应",
    "用户似乎把话留在心里，没有说出来",
    "这一刻没有来自用户的文字",
    "用户沉默着，场面没有被新话打断",
    "等待中：用户侧仍无声响",
)


def format_silence_log_line(
    *,
    when: datetime | None = None,
    phrase: str | None = None,
    rng: random.Random | None = None,
) -> str:
    ts = when or datetime.now()
    body = (phrase or "").strip()
    if not body:
        picker = rng if rng is not None else random
        body = picker.choice(SILENCE_OBSERVATION_PHRASES)
    return f"{ts.strftime('%Y-%m-%d %H:%M:%S')}——{body}"


@dataclass
class NarrativeStageCard:
    """叙事舞台卡：外在身份/活动 + 客观临场事件；禁止用户意图字段。"""

    user_identity: str = ""
    user_activity: str = ""
    scene_event: str = ""
    interaction_mode: str = ""
    turn_index: int = 0
    written_at: float = 0.0

    @property
    def ready(self) -> bool:
        return bool(
            self.user_identity.strip()
            or self.user_activity.strip()
            or self.scene_event.strip()
        )

    def render(self) -> str:
        lines: list[str] = []
        identity = self.user_identity.strip()
        activity = self.user_activity.strip()
        event = self.scene_event.strip()
        mode = self.interaction_mode.strip()
        if identity or activity or mode:
            lines.append("[用户舞台｜叙事导演]")
            if mode:
                lines.append(f"交互通道={mode}")
            if identity:
                lines.append(f"身份={identity}")
            if activity:
                lines.append(f"正在做={activity}")
        if event:
            lines.append("[临场事件｜客观纪要]")
            lines.append(event)
        return "\n".join(lines)

    def one_line(self, *, limit: int = 120) -> str:
        parts = [
            self.user_identity.strip() or "—",
            self.user_activity.strip() or "—",
            " ".join(self.scene_event.strip().split()) or "—",
        ]
        body = "｜".join(parts)
        if len(body) > limit:
            return body[: limit - 1] + "…"
        return body

    def snapshot(self) -> dict[str, Any]:
        return {
            "user_identity": self.user_identity,
            "user_activity": self.user_activity,
            "scene_event": self.scene_event,
            "interaction_mode": self.interaction_mode,
            "turn_index": self.turn_index,
            "written_at": self.written_at,
            "ready": self.ready,
        }

    @classmethod
    def from_dict(cls, raw: object) -> NarrativeStageCard | None:
        if not isinstance(raw, dict):
            return None
        card = cls(
            user_identity=str(raw.get("user_identity") or "").strip(),
            user_activity=str(raw.get("user_activity") or "").strip(),
            scene_event=str(raw.get("scene_event") or "").strip(),
            interaction_mode=str(raw.get("interaction_mode") or "").strip(),
            turn_index=int(raw.get("turn_index") or 0),
            written_at=float(raw.get("written_at") or 0.0),
        )
        if not card.ready:
            return None
        return card


@dataclass
class SilenceLog:
    """多轮静默元数据：时间——十条角度表述之一；真实用户输入时清零。"""

    entries: list[str] = field(default_factory=list)
    _rng: random.Random | None = field(default=None, repr=False, compare=False)

    def append_now(
        self,
        *,
        when: datetime | None = None,
        phrase: str | None = None,
    ) -> str:
        line = format_silence_log_line(when=when, phrase=phrase, rng=self._rng)
        self.entries.append(line)
        if len(self.entries) > _SILENCE_LOG_MAX:
            self.entries = self.entries[-_SILENCE_LOG_MAX:]
        return line

    def clear(self) -> None:
        self.entries.clear()

    @property
    def ready(self) -> bool:
        return bool(self.entries)

    def render(self) -> str:
        if not self.entries:
            return ""
        lines = [
            "[无用户输入卡·元数据]",
            *self.entries,
            "说明：以上为现场观察角度的时间戳记录；交由叙事侧合理化「静默」本身，"
            "避免杜撰用户外在动作；导演据此校验临场是否符合预期。"
            "通道：用户↔世界目前仅文字发言/静默可观测。",
        ]
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        return {"entries": list(self.entries), "count": len(self.entries)}
