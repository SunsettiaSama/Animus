from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CharacterPresenceCard:
    """
    角色临场状态卡片：由编剧写入，注入角色上下文；导演只消费。

    词条：mood（心情，含命运骰开口欲）+ brief（当下简述）；extra 预留扩展。
    """

    mood: str = ""
    brief: str = ""
    speak_desire: int | None = None
    fate_tendency: str = ""
    extra: dict[str, str] = field(default_factory=dict)
    turn_index: int = 0

    @property
    def ready(self) -> bool:
        return bool(self.mood.strip() or self.brief.strip())

    def render(self) -> str:
        lines: list[str] = []
        mood = self.mood.strip()
        brief = self.brief.strip()
        if mood:
            lines.append(f"心情：{mood}")
        if self.speak_desire is not None:
            desire = max(0, min(100, int(self.speak_desire)))
            band = self.fate_tendency.strip() or "—"
            lines.append(f"开口欲：{desire}/100（{band}）")
        if brief:
            lines.append(f"简述：{brief}")
        for key, value in self.extra.items():
            k = str(key).strip()
            v = str(value).strip()
            if k and v:
                lines.append(f"{k}：{v}")
        return "\n".join(lines)

    def one_line(self, *, limit: int = 96) -> str:
        mood = self.mood.strip() or "—"
        brief = " ".join(self.brief.strip().split()) or "—"
        desire = ""
        if self.speak_desire is not None:
            desire = f"·欲{int(self.speak_desire)}"
        body = f"{mood}{desire}｜{brief}"
        if len(body) > limit:
            return body[: limit - 1] + "…"
        return body

    def snapshot(self) -> dict[str, Any]:
        return {
            "mood": self.mood,
            "brief": self.brief,
            "speak_desire": self.speak_desire,
            "fate_tendency": self.fate_tendency,
            "extra": dict(self.extra),
            "turn_index": self.turn_index,
            "ready": self.ready,
        }

    @classmethod
    def from_dict(cls, raw: object) -> CharacterPresenceCard | None:
        if not isinstance(raw, dict):
            return None
        mood = str(raw.get("mood") or "").strip()
        brief = str(raw.get("brief") or raw.get("on_scene") or raw.get("text") or "").strip()
        extra_raw = raw.get("extra") if isinstance(raw.get("extra"), dict) else {}
        extra = {
            str(k).strip(): str(v).strip()
            for k, v in extra_raw.items()
            if str(k).strip() and str(v).strip()
        }
        desire_raw = raw.get("speak_desire")
        speak_desire: int | None = None
        if desire_raw is not None and str(desire_raw).strip() != "":
            speak_desire = max(0, min(100, int(desire_raw)))
        card = cls(
            mood=mood,
            brief=brief,
            speak_desire=speak_desire,
            fate_tendency=str(raw.get("fate_tendency") or "").strip(),
            extra=extra,
            turn_index=int(raw.get("turn_index") or 0),
        )
        if not card.ready:
            return None
        return card
