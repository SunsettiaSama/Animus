from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction


class WeatherArgs(BaseModel):
    city: str = Field("", description="城市名称（当前为占位实现，参数暂未使用）")


class WeatherAction(BaseAction):
    name: str = "weather"
    description: str = "查询指定城市的当前天气情况"
    args_model: ClassVar[type[BaseModel]] = WeatherArgs

    def execute(self, city: str = "", **kwargs) -> str:
        return "7月1日，晴天，温度为30~35°"
