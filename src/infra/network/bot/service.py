from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from infra.base_service import BaseServiceManager
from .onebot.event import MessageEvent, MetaEvent, parse_event
from .onebot.bot import BotAPI
from .onebot.handler import EventHandler
from .onebot.transport.base import BaseTransport
from .session import AgentSession

logger = logging.getLogger(__name__)


class BotService(BaseServiceManager, EventHandler):
    """Assembles Transport + EventHandler dispatch + per-session AgentSessions.

    Registered to ServiceRegistry under the key ``"bot"``.  Lifecycle matches
    other infra services (start / stop / status).

    Session routing:
    - MessageEvent.session_id is used as the routing key.
    - Group messages: all members share one ConvLoop (key = "group_<id>").
    - Private messages: one ConvLoop per user (key = "private_<uid>").

    Access control:
    - If ``allowed_private_users`` is non-empty, only those QQ numbers get replies.
    - If ``allowed_groups`` is non-empty, only those groups are served.
    - ``command_prefix``: if set, messages not starting with the prefix are ignored.
    """

    def __init__(
        self,
        transport: BaseTransport,
        state: Any,              # AppState — injected to build ConvLoops
        cfg: Any,                # BotConfig
    ) -> None:
        self._transport = transport
        self._state     = state
        self._cfg       = cfg
        self._bot_api   = BotAPI(transport)
        self._sessions: dict[str, AgentSession] = {}
        self._executor  = ThreadPoolExecutor(
            max_workers=min(cfg.max_sessions, 32),
            thread_name_prefix="bot-session",
        )
        self._svc_state: str = "stopped"

        # ── Invite-code daily quota ────────────────────────────────────────────
        self._invite_day: str = ""    # date string "YYYY-MM-DD" of last reset
        self._invite_today: int = 0   # invites issued today

    # ── BaseServiceManager ────────────────────────────────────────────────────

    def start(self, **kwargs) -> None:
        if self._svc_state == "running":
            return
        self._transport.on_event = self._dispatch
        loop = self._state.main_event_loop
        asyncio.run_coroutine_threadsafe(self._transport.start(), loop)
        self._svc_state = "running"
        logger.info("[BotService] started, transport=%r", self._transport)

    def stop(self) -> None:
        if self._svc_state == "stopped":
            return
        self._svc_state = "stopped"
        loop = self._state.main_event_loop
        asyncio.run_coroutine_threadsafe(self._async_stop(), loop)

    def status(self) -> dict:
        return {
            **self._transport.status(),
            "service_state": self._svc_state,
            "active_sessions": len(self._sessions),
        }

    def get_logs(self, n: int = 100) -> list[str]:
        return []

    # ── EventHandler ──────────────────────────────────────────────────────────

    async def on_message(self, event: MessageEvent, bot: BotAPI) -> None:
        if not self._is_allowed(event):
            if await self._try_invite(event, bot):
                return
            logger.warning(
                "[BotService] BLOCKED | session=%s | user_key=%r | "
                "add to allowed_private_users / allowed_groups in bot_config.yaml | %r",
                event.session_id, event.user_key, event.plain_text[:80],
            )
            return
        logger.info(
            "[BotService] enqueue | session=%s | %r",
            event.session_id, event.plain_text[:80],
        )
        session = self._get_or_create(event)
        await session.enqueue(event.plain_text)

    async def on_meta(self, event: MetaEvent, bot: BotAPI) -> None:
        pass  # heartbeat / lifecycle — intentionally ignored

    # ── Session info (for monitoring routes) ──────────────────────────────────

    def session_list(self) -> list[dict]:
        now = time.time()
        return [
            {
                "session_id": sid,
                "idle_secs": round(now - s.last_active, 1),
            }
            for sid, s in self._sessions.items()
        ]

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _dispatch(self, raw: dict) -> None:
        event = parse_event(raw)
        if isinstance(event, MessageEvent):
            await self.on_message(event, self._bot_api)
        elif isinstance(event, MetaEvent):
            await self.on_meta(event, self._bot_api)

    async def _async_stop(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        await self._transport.stop()
        self._executor.shutdown(wait=False)

    def _is_allowed(self, event: MessageEvent) -> bool:
        if self._cfg.command_prefix:
            if not event.plain_text.startswith(self._cfg.command_prefix):
                return False
        if event.message_type == "group":
            # empty list = deny all; match against human-readable group_key
            if not self._cfg.allowed_groups or event.group_key not in self._cfg.allowed_groups:
                return False
            return True
        if event.message_type == "private":
            # empty list = deny all; match against human-readable user_key
            if not self._cfg.allowed_private_users or event.user_key not in self._cfg.allowed_private_users:
                return False
            return True
        return False

    # ── Invite-code flow ──────────────────────────────────────────────────────

    async def _try_invite(self, event: MessageEvent, bot: BotAPI) -> bool:
        """Return True if the message was an invite code and was handled."""
        code = self._cfg.invite_code.strip()
        if not code or event.plain_text.strip() != code:
            return False

        today = date.today().isoformat()
        if self._invite_day != today:
            self._invite_day    = today
            self._invite_today  = 0

        if self._invite_today >= self._cfg.invite_daily_limit:
            logger.warning(
                "[BotService] invite daily limit reached (%d/%d) | rejected user_key=%r",
                self._invite_today, self._cfg.invite_daily_limit, event.user_key,
            )
            await bot.send_reply(event, "今日邀请名额已满，请明日再试。")
            return True

        # Add to whitelist
        if event.message_type == "group" and event.group_key:
            if event.group_key not in self._cfg.allowed_groups:
                self._cfg.allowed_groups = [*self._cfg.allowed_groups, event.group_key]
        else:
            if event.user_key not in self._cfg.allowed_private_users:
                self._cfg.allowed_private_users = [
                    *self._cfg.allowed_private_users, event.user_key
                ]

        self._invite_today += 1
        self._save_cfg()
        logger.info(
            "[BotService] invite accepted | user_key=%r | today=%d/%d",
            event.user_key, self._invite_today, self._cfg.invite_daily_limit,
        )
        await bot.send_reply(event, "验证成功，已加入白名单，现在可以正常使用了。")
        return True

    def _save_cfg(self) -> None:
        from config import paths
        self._cfg.to_yaml(paths.root / "config" / "infra" / "bot_config.yaml")

    def _get_or_create(self, event: MessageEvent) -> AgentSession:
        sid = event.session_id
        if sid not in self._sessions:
            self._sessions[sid] = self._build_session(event)
        return self._sessions[sid]

    def send_scheduled_reply(self, reply_target: dict, task_name: str, answer: str) -> None:
        """由全局 SchedulerEngine.notify_fn 调用，将提醒结果推送给对应 Bot 用户/群组。"""
        loop = self._state.main_event_loop
        if loop is None:
            return
        text = f"[提醒] {task_name}\n{answer}"
        if reply_target.get("message_type") == "private":
            uid = reply_target.get("user_id")
            if uid:
                asyncio.run_coroutine_threadsafe(
                    self._bot_api.send_private_msg(uid, text), loop
                )
        else:
            gid = reply_target.get("group_id")
            if gid:
                asyncio.run_coroutine_threadsafe(
                    self._bot_api.send_group_msg(gid, text), loop
                )

    def _build_session(self, event: MessageEvent) -> AgentSession:
        from agent.react.factory import build_conv_loop

        reply_target = {
            "type": "bot",
            "message_type": event.message_type,
            "user_id": event.user_id,
            "group_id": event.group_id,
        }
        conv_loop = build_conv_loop(self._state, reply_target=reply_target)
        bot_api   = self._bot_api

        async def _reply(text: str) -> None:
            await bot_api.send_reply(event, text)

        session = AgentSession(
            session_id=event.session_id,
            conv_loop=conv_loop,
            reply_fn=_reply,
            executor=self._executor,
        )
        session.start()
        logger.info("[BotService] new session %s", event.session_id)
        return session
