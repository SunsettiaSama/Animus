from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction
from ._rate_limiter import RateLimiter


class SendNotificationArgs(BaseModel):
    message: str = Field(..., min_length=1, description="通知内容")
    title: str = Field("Agent 通知", description="通知标题")
    channel: str = Field(
        "all",
        description="发送渠道：bark | ntfy | all（默认：all，同时发送到所有已配置渠道）",
    )


class SendNotificationAction(BaseAction):
    name: str = "send_notification"
    description: str = (
        "向用户发送推送通知（Bark / ntfy）。"
        "参数：message（通知内容），title（标题，默认'Agent 通知'），"
        "channel（bark | ntfy | all，默认 all）。"
        "受速率限制：超限时操作会被拒绝。"
    )
    args_model: ClassVar[type[BaseModel]] = SendNotificationArgs

    rate_cfg: Any = None  # dict with keys: notify_rpm, notify_rph

    def execute(
        self,
        message: str,
        title: str = "Agent 通知",
        channel: str = "all",
        **kwargs,
    ) -> str:
        rpm = 0
        rph = 0
        if self.rate_cfg is not None:
            rpm = int(self.rate_cfg.get("comm_notify_rpm", 0))
            rph = int(self.rate_cfg.get("comm_notify_rph", 0))

        RateLimiter.check("send_notification", rpm, rph)

        from webui.state import get_state
        state = get_state()

        sent_to: list[str] = []

        if channel in ("bark", "all") and state.bark_notifier is not None:
            state.bark_notifier.send(title=title, body=message)
            sent_to.append("Bark")

        if channel in ("ntfy", "all") and state.ntfy_notifier is not None:
            state.ntfy_notifier.send(title=title, body=message)
            sent_to.append("ntfy")

        if not sent_to:
            return f"没有可用的推送渠道（channel={channel!r}）。"
        return f"通知已发送至：{', '.join(sent_to)}。"
