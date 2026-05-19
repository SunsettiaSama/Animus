from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agent.react.action.base import BaseAction


class SoulLifeChronicleArgs(BaseModel):
    days: int = Field(7, ge=1, le=90, description="回溯天数")
    tail: int = Field(30, ge=1, le=200, description="最多返回条数")


class SoulLifeChronicleAction(BaseAction):
    """经 Soul 接口查看 Life 近期 Chronicle 经历账本。"""

    name: str = "soul_life_chronicle"
    description: str = (
        "查看 Life 近期经历。"
        "参数：days（默认 7），tail（最多条数，默认 30）。"
    )
    args_model: ClassVar[type[BaseModel]] = SoulLifeChronicleArgs

    soul: Any = None

    def execute(self, days: int = 7, tail: int = 30, **kwargs) -> str:
        if self.soul is None:
            return "Soul Life 服务未就绪。"
        entries = self.soul.query_life_chronicle(days=days, tail=tail)
        if not entries:
            return "（近期 Chronicle 为空）"
        lines = [
            f"[{e.get('ts', '')[:16]}] ({e.get('kind', '')}) {e.get('summary', '')}"
            for e in entries
        ]
        return "\n".join(lines)
