from __future__ import annotations

from dataclasses import dataclass, field

from .queue import ShareIntentQueue

import config.soul.presence.config as presence_cfg


@dataclass
class ExpectationState:
    """主动驱动会话：对用户的期待值 + 多次回复欲望 + 待分享队列。"""

    toward_user: float = 0.0
    reply_urge: float = 0.0
    reason: str = ""
    source: str = ""
    share_queue: ShareIntentQueue = field(default_factory=ShareIntentQueue)

    def accumulate_toward_user(
        self,
        delta: float,
        *,
        reason: str = "",
        source: str = "",
    ) -> None:
        if delta <= 0.0:
            return
        self.toward_user = min(1.0, self.toward_user + delta)
        if reason.strip():
            self.reason = reason.strip()
        if source.strip():
            self.source = source.strip()

    def accumulate_reply_urge(
        self,
        delta: float,
        *,
        reason: str = "",
        source: str = "",
    ) -> None:
        if delta <= 0.0:
            return
        self.reply_urge = min(1.0, self.reply_urge + delta)
        if reason.strip():
            self.reason = reason.strip()
        if source.strip():
            self.source = source.strip()

    def discharge_toward_user(self, amount: float) -> None:
        self.toward_user = max(0.0, self.toward_user - max(0.0, amount))
        if self.toward_user == 0.0:
            self._clear_meta()

    def discharge_reply_urge(self, amount: float) -> None:
        self.reply_urge = max(0.0, self.reply_urge - max(0.0, amount))
        if self.reply_urge == 0.0 and self.toward_user == 0.0:
            self._clear_meta()

    def reset_after_proactive_open(self) -> None:
        """主动发起会话后回落期待值并清空分享队列。"""
        self.toward_user = 0.0
        self.share_queue.drain()
        self._clear_meta()

    def at_proactive_threshold(
        self,
        threshold: float | None = None,
    ) -> bool:
        active = (
            presence_cfg.PROACTIVE_OPEN_THRESHOLD
            if threshold is None
            else threshold
        )
        return self.toward_user >= active

    def wants_multi_reply(
        self,
        threshold: float | None = None,
    ) -> bool:
        active = (
            presence_cfg.REPLY_URGE_THRESHOLD
            if threshold is None
            else threshold
        )
        return self.reply_urge >= active

    def render(self) -> str:
        parts: list[str] = []
        if self.toward_user > 0.0:
            parts.append(f"想和用户说话（{self.toward_user:.2f}）")
        if self.reply_urge > 0.0:
            parts.append(f"还想多说几句（{self.reply_urge:.2f}）")
        if self.reason.strip():
            parts.append(self.reason.strip())
        return "；".join(parts)

    def is_empty(self) -> bool:
        return (
            self.toward_user == 0.0
            and self.reply_urge == 0.0
            and self.share_queue.is_empty()
        )

    def copy(self) -> ExpectationState:
        return ExpectationState(
            toward_user=self.toward_user,
            reply_urge=self.reply_urge,
            reason=self.reason,
            source=self.source,
            share_queue=self.share_queue.copy(),
        )

    def to_dict(self) -> dict:
        return {
            "toward_user": round(self.toward_user, 4),
            "reply_urge": round(self.reply_urge, 4),
            "reason": self.reason,
            "source": self.source,
            "share_queue": self.share_queue.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ExpectationState:
        return cls(
            toward_user=float(d.get("toward_user", 0.0)),
            reply_urge=float(d.get("reply_urge", 0.0)),
            reason=str(d.get("reason", "")),
            source=str(d.get("source", "")),
            share_queue=ShareIntentQueue.from_dict(d.get("share_queue")),
        )

    def _clear_meta(self) -> None:
        self.reason = ""
        self.source = ""
