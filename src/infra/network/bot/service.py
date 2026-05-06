from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
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
            return
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
            if self._cfg.allowed_groups and event.group_id not in self._cfg.allowed_groups:
                return False
            return True
        if event.message_type == "private":
            if self._cfg.allowed_private_users and event.user_id not in self._cfg.allowed_private_users:
                return False
            return True
        return False

    def _get_or_create(self, event: MessageEvent) -> AgentSession:
        sid = event.session_id
        if sid not in self._sessions:
            self._sessions[sid] = self._build_session(event)
        return self._sessions[sid]

    def _build_session(self, event: MessageEvent) -> AgentSession:
        from agent.react.factory import build_conv_loop

        conv_loop = build_conv_loop(self._state)
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
