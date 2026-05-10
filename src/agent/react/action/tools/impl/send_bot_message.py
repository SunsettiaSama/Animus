from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction
from ._rate_limiter import RateLimiter


class SendBotMessageArgs(BaseModel):
    message: str = Field(..., min_length=1, description="要发送的消息内容")
    target_type: str = Field(
        ...,
        description="目标类型：private（私聊）| group（群聊）",
    )
    target_id: int = Field(
        ...,
        description="目标 ID：私聊时为用户 QQ 号，群聊时为群号",
    )


class SendBotMessageAction(BaseAction):
    name: str = "send_bot_message"
    description: str = (
        "通过 Bot 发送消息（QQ 私聊或群聊）。"
        "参数：message（消息内容），target_type（private | group），target_id（用户 QQ 或群号）。"
        "受速率限制：超限时操作会被拒绝。"
    )
    args_model: ClassVar[type[BaseModel]] = SendBotMessageArgs

    bot_service: Any = None       # BotService
    main_event_loop: Any = None   # asyncio.AbstractEventLoop | None
    rate_cfg: Any = None          # dict with keys: comm_bot_rpm, comm_bot_rph

    def execute(
        self,
        message: str,
        target_type: str,
        target_id: int,
        **kwargs,
    ) -> str:
        rpm = 0
        rph = 0
        if self.rate_cfg is not None:
            rpm = int(self.rate_cfg.get("comm_bot_rpm", 0))
            rph = int(self.rate_cfg.get("comm_bot_rph", 0))

        RateLimiter.check("send_bot_message", rpm, rph)

        if self.bot_service is None:
            return "Bot 服务未初始化，无法发送消息。"

        bot_api = self.bot_service._bot_api
        loop = self.main_event_loop

        if target_type == "private":
            coro = bot_api.send_private_msg(user_id=target_id, msg=message)
        elif target_type == "group":
            coro = bot_api.send_group_msg(group_id=target_id, msg=message)
        else:
            return f"不支持的 target_type：{target_type!r}，请使用 private 或 group。"

        if loop is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            fut.result(timeout=10)
        else:
            asyncio.run(coro)

        return f"消息已发送至 {target_type} {target_id}。"
