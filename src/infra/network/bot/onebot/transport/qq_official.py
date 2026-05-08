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

        # botpy 线程实际探测到的出口 IP（连 QQ 前通过 aiohttp 探测，与 botpy 使用同一代理）
        self._outbound_ip: str | None = None

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
        # 清空引用，确保 stop 后 call_action / send_text 快速失败而非对关闭的 loop 投递
        self._client   = None
        self._bot_loop = None

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
        return {
            "state":       self._state,
            "appid":       self._appid,
            "outbound_ip": self._outbound_ip,
        }

    # ── botpy 后台线程 ────────────────────────────────────────────────────────

    def _run_botpy(self) -> None:
        import botpy  # type: ignore[import]

        from config import paths
        from botpy.logging import DEFAULT_FILE_HANDLER

        # botpy 底层使用 aiohttp，aiohttp.ClientSession 默认 trust_env=False，
        # 不会自动读取 HTTP_PROXY / HTTPS_PROXY 等系统代理环境变量。
        # 此处 monkey-patch 使其默认开启 trust_env，从而让代理环境变量对 botpy 生效。
        import os as _os
        import aiohttp as _aiohttp
        _orig_cs_init = _aiohttp.ClientSession.__init__

        def _trust_env_init(self, *args, **kwargs):
            kwargs.setdefault("trust_env", True)
            _orig_cs_init(self, *args, **kwargs)

        _aiohttp.ClientSession.__init__ = _trust_env_init

        # 若配置文件指定了代理，写入环境变量供 trust_env 读取；
        # 不覆盖用户已手动设置的同名变量。
        from config.infra.bot_config import BotConfig as _BotConfig
        _cfg_proxy = _BotConfig.load().proxy.strip()
        if _cfg_proxy:
            _os.environ.setdefault("HTTP_PROXY",  _cfg_proxy)
            _os.environ.setdefault("HTTPS_PROXY", _cfg_proxy)
            logger.info("[QQOfficialTransport] using proxy: %s", _cfg_proxy)

        # botpy v1.2.1 已知 bug：任意 API 请求超时时，botpy/http.py 的 request()
        # 捕获 TimeoutError 后仅打印警告并 return None，调用方没有防御判空。
        # 根源修复：patch BotHttp.request，对 None 结果自动重试，覆盖所有 API 调用。
        # Ref: https://github.com/AstrBotDevs/AstrBot/issues/6858
        import asyncio as _asyncio
        import botpy.http as _botpy_http
        _orig_request = _botpy_http.BotHttp.request

        async def _retrying_request(http_self, route, **kwargs):
            for _attempt in range(1, 6):
                result = await _orig_request(http_self, route, **kwargs)
                if result is not None:
                    return result
                logger.warning(
                    "[QQOfficialTransport] %s %s 返回 None"
                    "（尝试 %d/5，可能是网络超时），5 秒后重试…",
                    route.method, route.path, _attempt,
                )
                await _asyncio.sleep(5)
            raise RuntimeError(
                f"{route.method} {route.path} 连续 5 次返回 None，"
                "请检查网络连通性或代理设置"
            )

        _botpy_http.BotHttp.request = _retrying_request

        # Redirect botpy file log from cwd to .react/logs/
        _log_dir = paths.cache_root / "logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
        _file_handler = {
            **DEFAULT_FILE_HANDLER,
            "filename": str(_log_dir / "%(name)s.log"),
        }

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
                content = getattr(message, "content", "") or ""
                logger.info(
                    "[QQ←C2C ] uid=%d | msg_id=%s | %r",
                    uid, message.id, content[:100],
                )
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
                content = getattr(message, "content", "") or ""
                logger.info(
                    "[QQ←GROUP] gid=%d uid=%d | msg_id=%s | %r",
                    gid, uid, message.id, content[:100],
                )
                transport._session_ctx[sid] = _SessionCtx(
                    target_id=group_openid,
                    last_msg_id=message.id,
                )
                raw = transport._group_to_onebot(message, gid, uid)
                transport._fire(raw)

        loop = asyncio.new_event_loop()
        loop.set_exception_handler(
            lambda _loop, ctx: logger.error(
                "[QQOfficialTransport] unhandled async error: %s",
                ctx.get("message", "unknown"),
                exc_info=ctx.get("exception"),
            )
        )
        asyncio.set_event_loop(loop)
        self._bot_loop = loop

        # public_messages 对应官方 Intent 中的 GROUP_AND_C2C_EVENT (bit 25)
        # qq-botpy <=1.2.x 中该旗标名为 public_messages，高版本改名为 group_and_c2c_event
        intents       = botpy.Intents(public_messages=True)
        self._client  = _QQClient(
            intents=intents,
            is_sandbox=self._is_sandbox,
            ext_handlers=_file_handler,
        )

        async def _probe_ip() -> None:
            # 探测实际出口 IP——仅供日志参考，失败不影响 bot 启动。
            _timeout = _aiohttp.ClientTimeout(total=8)
            async with _aiohttp.ClientSession(timeout=_timeout) as _sess:
                async with _sess.get("https://api.ipify.org?format=json") as _r:
                    _d = await _r.json(content_type=None)
                    self._outbound_ip = _d.get("ip", "unknown")
            logger.info(
                "[QQOfficialTransport] botpy 实际出口 IP: %s  "
                "（若与 QQ 开放平台白名单不符，请更新白名单或配置代理）",
                self._outbound_ip,
            )

        def _on_probe_done(t: _asyncio.Task) -> None:
            if not t.cancelled() and t.exception() is not None:
                logger.warning(
                    "[QQOfficialTransport] 出口 IP 探测失败（网络不通或代理未就绪）: %s",
                    t.exception(),
                )
            if self._outbound_ip is None:
                self._outbound_ip = "unknown"

        async def _probe_then_start() -> None:
            # 以后台 Task 运行 IP 探测，不阻塞 bot 启动；
            # 超时或网络异常由 _on_probe_done 回调处理。
            probe = loop.create_task(_probe_ip())
            probe.add_done_callback(_on_probe_done)
            await self._client.start(appid=self._appid, secret=self._secret)

        loop.run_until_complete(_probe_then_start())
        self._state = "stopped"
        logger.warning("[QQOfficialTransport] botpy loop exited, transport stopped")

    def _fire(self, raw: dict) -> None:
        """跨线程将事件投递到主 event loop。"""
        if self.on_event and self._main_loop:
            fut = asyncio.run_coroutine_threadsafe(
                self.on_event(raw), self._main_loop
            )
            fut.add_done_callback(
                lambda f: logger.error(
                    "[QQOfficialTransport] dispatch error: %s", f.exception()
                ) if not f.cancelled() and f.exception() else None
            )

    # ── BaseTransport: high-level send_text ───────────────────────────────────

    async def send_text(self, target: dict, text: str) -> None:
        """Send a plain-text message, bridging from the main loop to the bot loop."""
        if self._client is None or self._bot_loop is None:
            raise RuntimeError(
                f"QQOfficialTransport not running (state={self._state})"
            )
        if target.get("message_type") == "group" and target.get("group_id") is not None:
            cf = asyncio.run_coroutine_threadsafe(
                self._do_send_group(target["group_id"], text),
                self._bot_loop,
            )
        else:
            cf = asyncio.run_coroutine_threadsafe(
                self._do_send_c2c(target["user_id"], text),
                self._bot_loop,
            )
        # 不设外层 timeout：_retrying_request 在 5 次失败后会 raise RuntimeError，
        # 届时异常由 _send_loop 的 future.result() 捕获，线程退出后由 _run_forever 重建。
        # 若在此加 wait_for timeout，会在重试 sleep 期间提前 cancel cf，
        # 导致 TimeoutError 早于 RuntimeError 到达，且 BOT_LOOP 中的协程状态不一致。
        await asyncio.wrap_future(cf)

    # ── 在 botpy loop 中执行 API 调用 ─────────────────────────────────────────

    async def _do_send_c2c(self, uid: int, text: str) -> str:
        """Send a C2C (private) message. Runs inside the botpy event loop."""
        ctx = self._session_ctx.get(f"private_{uid}")
        if ctx is None:
            raise RuntimeError(
                f"No active C2C session for user_id={uid}; "
                "user must send a message first (passive-reply only)"
            )
        logger.info("[QQ→C2C ] uid=%d | seq=%d | %r", uid, ctx.msg_seq, text[:100])
        result = await self._client.api.post_c2c_message(
            openid=ctx.target_id,
            msg_type=0,
            content=text,
            msg_id=ctx.last_msg_id,
            msg_seq=ctx.msg_seq,
        )
        ctx.msg_seq += 1
        logger.info("[QQ→C2C ] result: %r", result)
        return (result or {}).get("id", "")

    async def _do_send_group(self, gid: int, text: str) -> str:
        """Send a group message. Runs inside the botpy event loop."""
        ctx = self._session_ctx.get(f"group_{gid}")
        if ctx is None:
            raise RuntimeError(
                f"No active group session for group_id={gid}; "
                "user must @bot first (passive-reply only)"
            )
        logger.info("[QQ→GROUP] gid=%d | seq=%d | %r", gid, ctx.msg_seq, text[:100])
        result = await self._client.api.post_group_message(
            group_openid=ctx.target_id,
            msg_type=0,
            content=text,
            msg_id=ctx.last_msg_id,
            msg_seq=ctx.msg_seq,
        )
        ctx.msg_seq += 1
        return (result or {}).get("id", "")

    async def _do_call_action(self, action: str, params: dict) -> dict:
        if action == "send_private_msg":
            msg_id = await self._do_send_c2c(params["user_id"], str(params["message"]))
            return {"status": "ok", "data": {"message_id": msg_id}}

        if action == "send_group_msg":
            msg_id = await self._do_send_group(params["group_id"], str(params["message"]))
            return {"status": "ok", "data": {"message_id": msg_id}}

        return {
            "status": "failed",
            "retcode": 1404,
            "message": f"unsupported action: {action}",
        }

    # ── OneBot 11 格式转换 ────────────────────────────────────────────────────

    def _c2c_to_onebot(self, message: Any, uid: int) -> dict:
        content = getattr(message, "content", "") or ""
        openid  = message.author.user_openid
        return {
            "post_type":    "message",
            "message_type": "private",
            "sub_type":     "friend",
            "time":         self._parse_ts(message),
            "self_id":      0,
            "user_id":      uid,
            "user_key":     openid,          # raw openid — used for whitelist matching
            "message":      [{"type": "text", "data": {"text": content}}],
            "raw_message":  content,
            "message_id":   _openid_to_id(message.id),
            "font":         0,
            "sender": {
                "user_id":  uid,
                "nickname": getattr(
                    getattr(message, "author", None), "username", ""
                ),
            },
        }

    def _group_to_onebot(self, message: Any, gid: int, uid: int) -> dict:
        raw_content  = getattr(message, "content", "") or ""
        content      = _AT_RE.sub("", raw_content).strip()
        group_openid = message.group_openid
        user_openid  = message.author.member_openid
        return {
            "post_type":    "message",
            "message_type": "group",
            "sub_type":     "normal",
            "time":         self._parse_ts(message),
            "self_id":      0,
            "group_id":     gid,
            "user_id":      uid,
            "user_key":     user_openid,     # raw openid — used for whitelist matching
            "group_key":    group_openid,    # raw group openid — used for whitelist matching
            "message":      [{"type": "text", "data": {"text": content}}],
            "raw_message":  content,
            "message_id":   _openid_to_id(message.id),
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
