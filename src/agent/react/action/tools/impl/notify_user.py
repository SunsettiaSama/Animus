from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction


class NotifyUserArgs(BaseModel):
    message: str = Field(..., description="要发送给用户的消息正文")
    title: str = Field("", description="消息标题（可选，默认为空）")


class NotifyUserAction(BaseAction):
    name: str = "notify_user"
    description: str = (
        "在任务执行过程中向用户发送一条即时消息（用于汇报进度、传递中间结果或提示用户注意）。"
        "消息自动通过本任务绑定的渠道（WebUI 通知栏 / 机器人）投递，无需指定渠道，同时写入工作日志。"
        "参数：message（消息正文），title（可选标题）。"
    )
    args_model: ClassVar[type[BaseModel]] = NotifyUserArgs

    notify_fn: Any = None

    def execute(self, message: str, title: str = "", **kwargs) -> str:
        if self.notify_fn is not None:
            self.notify_fn(title, message)
        return "消息已发送"
