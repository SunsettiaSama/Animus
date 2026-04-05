from __future__ import annotations

from react.action.base import BaseAction


class WeatherAction(BaseAction):
    name = "weather"

    def execute(self, **kwargs) -> str:
        return "7月1日，晴天，温度为30~35°"
