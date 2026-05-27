from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agent.react.action.base import BaseAction


class SoulLifeHotArgs(BaseModel):
    hours: int = Field(2, ge=1, le=48, description="热存储窗口（小时）")


class SoulLifeHotAction(BaseAction):
    """经 Soul 接口查看 Life 当前热存储体验。"""

    name: str = "soul_life_hot"
    description: str = (
        "查看 Life 的近期主观体验。"
        "参数：hours（默认 2）。"
    )
    args_model: ClassVar[type[BaseModel]] = SoulLifeHotArgs

    soul: Any = None

    def execute(self, hours: int = 2, **kwargs) -> str:
        if self.soul is None:
            return "Soul Life 服务未就绪。"
        units = self.soul.query_life_hot(hours=hours)
        if not units:
            return "（热存储为空）"
        lines: list[str] = []
        for u in units:
            feeling = (u.get("feeling") or {})
            situation = (u.get("situation") or {})
            salience = feeling.get("salience", 0)
            narration = situation.get("narration") or situation.get("perception") or ""
            emotion = feeling.get("emotion_label") or ""
            lines.append(
                f"[{u.get('ts', '')[:16]}] sal={salience:.2f} {emotion} {str(narration)[:160]}"
            )
        return "\n".join(lines)
