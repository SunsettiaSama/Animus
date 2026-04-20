from __future__ import annotations

from react.action.base import BaseAction


class WeatherAction(BaseAction):
    name: str = "weather"
    description: str = "查询指定城市的当前天气情况"

    def execute(self, **kwargs) -> str:
        return "7月1日，晴天，温度为30~35°"
