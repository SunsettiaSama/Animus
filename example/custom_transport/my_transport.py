"""
自定义 Transport 示例
=====================
演示如何为任意平台（Telegram / Discord / HTTP Webhook 等）实现
BaseTransport，从而接入 BotService 而无需修改上层代码。

运行前需安装示例依赖：
    pip install aiohttp

本示例模拟一个 HTTP Long-Poll 平台：
- 平台通过 GET /events 推送事件（返回 OneBot 11 格式 JSON）
- 平台通过 POST /actions 接收动作调用
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import aiohttp

# ── 将 src/ 加入 sys.path，使 infra 包可被直接导入 ───────────────────────────

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from infra.network.bot.onebot.transport.base import BaseTransport

logger = logging.getLogger(__name__)


class HttpPollTransport(BaseTransport):
    """HTTP Long-Poll 传输示例。

    模拟一个"自定义平台"：
    - 每隔 1 秒向 base_url/events 轮询事件
    - 动作调用向 base_url/actions 发送 POST

    只要你的平台能提供 OneBot 11 格式的事件和动作接口，
    就可以用这个 Transport 接入 BotService。
    """

    def __init__(self, base_url: str, token: str = "") -> None:
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._token    = token
        self._state    = "stopped"
        self._task: asyncio.Task | None = None
        self._session: aiohttp.ClientSession | None = None

    # ── BaseTransport interface ───────────────────────────────────────────────

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self._token}"} if self._token else {}
        )
        self._state = "connecting"
        self._task  = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._state = "stopped"
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._session:
            await self._session.close()
            self._session = None

    async def call_action(self, action: str, params: dict, timeout: float = 10.0) -> dict:
        if self._session is None:
            raise RuntimeError("Transport not started")
        payload = {"action": action, "params": params, "echo": str(uuid.uuid4())}
        async with self._session.post(
            f"{self._base_url}/actions",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            return await resp.json()

    def status(self) -> dict:
        return {"state": self._state, "url": self._base_url}

    # ── Internal poll loop ────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        self._state = "running"
        while self._state == "running":
            events = await self._fetch_events()
            for raw in events:
                if self.on_event is not None:
                    await self.on_event(raw)
            await asyncio.sleep(1.0)

    async def _fetch_events(self) -> list[dict]:
        if self._session is None:
            return []
        try:
            async with self._session.get(
                f"{self._base_url}/events",
                timeout=aiohttp.ClientTimeout(total=5.0),
            ) as resp:
                return await resp.json()
        except Exception as exc:
            logger.warning("[HttpPollTransport] poll failed: %s", exc)
            return []


# ── 使用示例（standalone，不依赖 FastAPI）────────────────────────────────────

async def _demo() -> None:
    """
    以 standalone 方式运行 BotService，不启动 WebUI。

    前提：
    1. 已配置 LLM（config/llm_core/config.yaml 存在且 model 非空）
    2. 你有一个实现了 OneBot 11 HTTP 接口的平台在 http://localhost:9000 运行
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

    from config.infra.bot_config import BotConfig
    from webui.state import get_state

    state   = get_state()
    bot_cfg = BotConfig(ws_url="http://localhost:9000", max_sessions=10)

    transport   = HttpPollTransport(base_url="http://localhost:9000")
    bot_service = state.bot_service  # already created in state._init_infra

    # Swap transport if needed
    from infra.network.bot.service import BotService
    custom_service = BotService(transport=transport, state=state, cfg=bot_cfg)

    # Start inside an asyncio loop
    await transport.start()
    print("Custom HttpPollTransport started, press Ctrl+C to stop")
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await transport.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_demo())
