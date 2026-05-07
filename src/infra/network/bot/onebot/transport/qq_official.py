"""QQ 官方机器人 Transport

基于腾讯 qq-botpy SDK 接入 QQ 开放平台机器人 API（https://bot.q.qq.com/），
无需 NapCat / Lagrange 等外部进程。

安装依赖：
    pip install qq-botpy

前提：
    在 QQ 开放平台（https://q.qq.com/）注册机器人，获得 AppID 与 AppSecret。

支持场景：
    - QQ 私聊（C2C）消息：on_c2c_message_create
    - QQ 群 @机器人 消息：on_group_at_message_create

重要限制（官方 API 规则）：
    - 群消息：被动回复有效期 5 分钟，每条 msg_id 最多回复 5 次
    - 私聊：被动回复有效期 60 分钟，每条 msg_id 最多回复 5 次
    - 无法获取真实 QQ 号，user_id / group_id 使用 openid 的 MD5 摘要整数表示
    - 群消息只在 @机器人 时触发

与 OneBot 11 的差异：
    call_action("send_private_msg", {"user_id": uid, ...})
    call_action("send_group_msg",   {"group_id": gid, ...})
    —— uid / gid 均为本模块生成的伪整数，非真实 QQ 号
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any

from .base import BaseTransport

logger = logging.getLogger(__name__)

# 剥离群消息中 "@机器人" 的 CQ 片段，如 <@!12345> 或 <@12345>
_AT_RE = re.compile(r"<@!?\d+>\s*")


def _openid_to_id(openid: str) -> int:
    """将 openid 字符串稳定映射为正整数（MD5 前 7 字节）。

    使用 MD5 而非 hash()，确保跨进程重启后结果一致。
    """
    digest = hashlib.md5(openid.encode()).digest()
    return int.from_bytes(digest[:7], "big")


@dataclass
class _SessionCtx:
    """单个会话的发送上下文，用于构造被动回复。"""

    target_id: str   # 实际 openid 或 group_openid
    last_msg_id: str # 最近一条入站消息的 id（被动回复必须携带）
    msg_seq: int = 1 # 同一 msg_id 下的回复序号，每次 +1 防重发


class QQOfficialTransport(BaseTransport):
    """QQ 官方机器人 Transport。

    生命周期：
        start() 启动一个后台线程，在新 event loop 中运行 botpy client；
        stop()  通知 botpy client 关闭，等待线程退出；
        call_action() 在主 loop 中通过 asyncio.wrap_future 跨线程调用 botpy API。

    事件路由：
        botpy 回调 → _SessionCtx 更新 → 格式转换为 OneBot 11 dict → on_event(raw)
    """

    def __init__(
        self,
        appid: str,
        secret: str,
        is_sandbox: bool = False,
    ) -> None:
        super().__init__()
        self._appid      = appid
        self._secret     = secret
        self._is_sandbox = is_sandbox
        self._state      = "stopped"

        self._client:   Any                              = None
        self._bot_loop: asyncio.AbstractEventLoop | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._thread:   threading.Thread | None          = None

        # session_id → 发送上下文
        self._session_ctx: dict[str, _SessionCtx] = {}

    # ── BaseTransport ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._main_loop = asyncio.get_running_loop()
        self._state     = "connecting"
        self._thread    = threading.Thread(
            target=self._run_botpy,
            daemon=True,
            name="qq-official-bot",
        )
        self._thread.start()

    async def stop(self) -> None:
        self._state = "stopped"
        if self._client is not None and self._bot_loop is not None:
            if not self._bot_loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self._client.close(), self._bot_loop
                ).result(timeout=5)
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    async def call_action(
        self,
        action: str,
        params: dict,
        timeout: float = 10.0,
    ) -> dict:
        if self._client is None or self._bot_loop is None:
            raise RuntimeError(
                f"QQOfficialTransport not running (state={self._state})"
            )
        cf = asyncio.run_coroutine_threadsafe(
            self._do_call_action(action, params),
            self._bot_loop,
        )
        return await asyncio.wait_for(asyncio.wrap_future(cf), timeout)

    def status(self) -> dict:
        return {"state": self._state, "appid": self._appid}

    # ── botpy 后台线程 ────────────────────────────────────────────────────────

    def _run_botpy(self) -> None:
        import botpy  # type: ignore[import]

        transport = self

        class _QQClient(botpy.Client):
            async def on_ready(self) -> None:
                transport._state = "running"
                logger.info(
                    "[QQOfficialTransport] connected, appid=%s", transport._appid
                )

            async def on_c2c_message_create(self, message: Any) -> None:
                openid = message.author.user_openid
                uid    = _openid_to_id(openid)
                sid    = f"private_{uid}"
                transport._session_ctx[sid] = _SessionCtx(
                    target_id=openid,
                    last_msg_id=message.id,
                )
                raw = transport._c2c_to_onebot(message, uid)
                transport._fire(raw)

            async def on_group_at_message_create(self, message: Any) -> None:
                group_openid = message.group_openid
                user_openid  = message.author.member_openid
                gid = _openid_to_id(group_openid)
                uid = _openid_to_id(user_openid)
                sid = f"group_{gid}"
                transport._session_ctx[sid] = _SessionCtx(
                    target_id=group_openid,
                    last_msg_id=message.id,
                )
                raw = transport._group_to_onebot(message, gid, uid)
                transport._fire(raw)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._bot_loop = loop

        # group_and_c2c_event 对应官方 Intent 中的 GROUP_AND_C2C_EVENT (bit 25)
        intents       = botpy.Intents(group_and_c2c_event=True)
        self._client  = _QQClient(intents=intents, is_sandbox=self._is_sandbox)

        loop.run_until_complete(
            self._client.start(appid=self._appid, secret=self._secret)
        )

    def _fire(self, raw: dict) -> None:
        """跨线程将事件投递到主 event loop。"""
        if self.on_event and self._main_loop:
            asyncio.run_coroutine_threadsafe(
                self.on_event(raw), self._main_loop
            )

    # ── 在 botpy loop 中执行 API 调用 ─────────────────────────────────────────

    async def _do_call_action(self, action: str, params: dict) -> dict:
        api = self._client.api

        if action == "send_private_msg":
            uid = params["user_id"]
            ctx = self._session_ctx.get(f"private_{uid}")
            if ctx is None:
                raise RuntimeError(
                    f"No active C2C session for user_id={uid}; "
                    "user must send a message first (passive-reply only)"
                )
            result = await api.post_c2c_message(
                openid=ctx.target_id,
                msg_type=0,
                content=str(params["message"]),
                msg_id=ctx.last_msg_id,
                msg_seq=ctx.msg_seq,
            )
            ctx.msg_seq += 1
            return {
                "status": "ok",
                "data": {"message_id": (result or {}).get("id", "")},
            }

        if action == "send_group_msg":
            gid = params["group_id"]
            ctx = self._session_ctx.get(f"group_{gid}")
            if ctx is None:
                raise RuntimeError(
                    f"No active group session for group_id={gid}; "
                    "user must @bot first (passive-reply only)"
                )
            result = await api.post_group_message(
                group_openid=ctx.target_id,
                msg_type=0,
                content=str(params["message"]),
                msg_id=ctx.last_msg_id,
                msg_seq=ctx.msg_seq,
            )
            ctx.msg_seq += 1
            return {
                "status": "ok",
                "data": {"message_id": (result or {}).get("id", "")},
            }

        return {
            "status": "failed",
            "retcode": 1404,
            "message": f"unsupported action: {action}",
        }

    # ── OneBot 11 格式转换 ────────────────────────────────────────────────────

    def _c2c_to_onebot(self, message: Any, uid: int) -> dict:
        content = getattr(message, "content", "") or ""
        return {
            "post_type":    "message",
            "message_type": "private",
            "sub_type":     "friend",
            "time":         self._parse_ts(message),
            "self_id":      0,
            "user_id":      uid,
            "message":      [{"type": "text", "data": {"text": content}}],
            "raw_message":  content,
            "message_id":   message.id,
            "font":         0,
            "sender": {
                "user_id":  uid,
                "nickname": getattr(
                    getattr(message, "author", None), "username", ""
                ),
            },
        }

    def _group_to_onebot(self, message: Any, gid: int, uid: int) -> dict:
        raw_content = getattr(message, "content", "") or ""
        content     = _AT_RE.sub("", raw_content).strip()
        return {
            "post_type":    "message",
            "message_type": "group",
            "sub_type":     "normal",
            "time":         self._parse_ts(message),
            "self_id":      0,
            "group_id":     gid,
            "user_id":      uid,
            "message":      [{"type": "text", "data": {"text": content}}],
            "raw_message":  content,
            "message_id":   message.id,
            "font":         0,
            "sender": {
                "user_id":  uid,
                "nickname": "",
                "card":     "",
                "role":     "member",
            },
        }

    @staticmethod
    def _parse_ts(message: Any) -> int:
        ts = getattr(message, "timestamp", None)
        if ts is None:
            return 0
        if isinstance(ts, (int, float)):
            return int(ts)
        from datetime import datetime, timezone
        return int(datetime.fromisoformat(str(ts)).astimezone(timezone.utc).timestamp())

    def __repr__(self) -> str:
        return f"<QQOfficialTransport appid={self._appid!r} state={self._state}>"
