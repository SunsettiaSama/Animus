from __future__ import annotations

import asyncio

from webui.state import AppState


def test_shutdown_wakes_speak_inbound_queue():
    async def _run() -> None:
        state = AppState()
        q: asyncio.Queue = asyncio.Queue()
        detach = state.attach_speak_inbound_queue(q)
        state.prepare_graceful_shutdown()
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
        detach()
        assert msg["type"] == "close"
        assert msg.get("reason") == "shutdown"

    asyncio.run(_run())
