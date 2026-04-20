from __future__ import annotations

from datetime import datetime, timezone, timedelta

from react.action.base import BaseAction

_TIMEZONES = {
    "utc": 0, "beijing": 8, "shanghai": 8, "cn": 8,
    "tokyo": 9, "jp": 9, "london": 0, "uk": 0,
    "new_york": -5, "us_east": -5, "us_west": -8,
    "paris": 1, "berlin": 1, "sydney": 10,
}


class GetDatetimeAction(BaseAction):
    name: str = "get_datetime"
    description: str = "获取当前日期和时间。参数：tz（可选，时区名称，如 'beijing'、'utc'、'tokyo'，默认为北京时间）"

    def execute(self, tz: str = "beijing", **kwargs) -> str:
        offset_hours = _TIMEZONES.get(tz.lower().strip(), 8)
        tz_obj = timezone(timedelta(hours=offset_hours))
        now = datetime.now(tz_obj)
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekdays[now.weekday()]
        sign = "+" if offset_hours >= 0 else ""
        return (
            f"当前时间（UTC{sign}{offset_hours}）：\n"
            f"日期：{now.strftime('%Y年%m月%d日')}  {weekday}\n"
            f"时间：{now.strftime('%H:%M:%S')}"
        )


class GetWeekdayAction(BaseAction):
    name: str = "get_weekday"
    description: str = "查询某个日期是星期几。参数：date（字符串，格式 'YYYY-MM-DD'，如 '2024-06-01'）"

    def execute(self, date: str = "", **kwargs) -> str:
        if not date:
            raise ValueError("缺少参数 date")
        dt = datetime.strptime(date.strip(), "%Y-%m-%d")
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekdays[dt.weekday()]
        return f"{date} 是 {weekday}（第 {dt.isocalendar()[1]} 周）"
