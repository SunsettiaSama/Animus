from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel, Field

from agent.soul.speak.io.outbound.stream import SpeakStreamEvent
from state import get_state

from .soul import _resolve_soul, _soul_or_400

router = APIRouter()

WEBUI_SPEAK_SESSION_ID = "webui"


class SpeakResetRequest(BaseModel):
    session_id: str = Field(default=WEBUI_SPEAK_SESSION_ID)


class WebUISpeakStreamPort:
    """将 SpeakStreamEvent 桥接到 asyncio 队列，供 WebSocket 推送。"""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
        *,
        gen_id: str,
    ) -> None:
        self._loop = loop
        self._queue = queue
        self._gen_id = gen_id
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        if self._closed:
            return
        payload = {
            "type": "speak_event",
            "gen_id": self._gen_id,
            "session_id": session_id,
            "kind": event.kind,
            "text": event.text,
            "final": event.final,
            "meta": dict(event.meta),
        }
        self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)


def _serialize_turn_result(result) -> dict[str, Any]:
    output = result.output.to_dict() if result.output is not None else {}
    return {
        "session_id": result.session_id,
        "answer": result.answer,
        "session_state": result.meta.get("session_state", "finish"),
        "queued": bool(result.meta.get("queued", False)),
        "interrupt": bool(result.meta.get("interrupt", False)),
        "recorded": result.recorded,
        "notes": list(result.notes),
        "output": output,
    }


@router.get("/api/speak/status")
def get_speak_status():
    soul = _resolve_soul()
    if soul is None:
        return {"status": "unavailable", "ready": False, "reason": "Soul 未初始化"}
    running = soul.is_running
    speak = None
    if running:
        speak = soul._ensure_speak_service()
    return {
        "status": "ready" if running and speak is not None else "idle",
        "ready": running and speak is not None,
        "soul_state": soul.state,
        "session_id": WEBUI_SPEAK_SESSION_ID,
    }


@router.post("/api/speak/reset")
def reset_speak_session(body: SpeakResetRequest | None = None):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    session_id = WEBUI_SPEAK_SESSION_ID
    if body is not None and body.session_id.strip():
        session_id = body.session_id.strip()
    closed = soul.close_dialogue_interaction(session_id)
    opened = soul.start_dialogue_session(session_id)
    return {
        "ok": True,
        "session_id": session_id,
        "closed": closed,
        "opened": opened,
    }


@router.websocket("/ws/speak/run")
async def ws_speak_run(websocket: WebSocket) -> None:
    state = get_state()
    await websocket.accept()

    data = await websocket.receive_json()
    question = str(data.get("question", "")).strip()
    gen_id = str(data.get("gen_id", ""))
    session_id = str(data.get("session_id", WEBUI_SPEAK_SESSION_ID)).strip() or WEBUI_SPEAK_SESSION_ID

    if not question:
        await websocket.send_json({"type": "error", "message": "empty question"})
        await websocket.close()
        return

    soul, err = _soul_or_400()
    if err is not None:
        await websocket.send_json({"type": "error", "message": "Soul 未就绪"})
        await websocket.close()
        return

    if not soul.is_running:
        await websocket.send_json({"type": "error", "message": "Soul 未运行"})
        await websocket.close()
        return

    if not state.try_start_streaming(gen_id):
        await websocket.send_json({"type": "error", "message": "Already streaming."})
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    event_q: asyncio.Queue = asyncio.Queue()
    port = WebUISpeakStreamPort(loop, event_q, gen_id=gen_id)
    soul.bind_speak_stream_port(port)

    turn_payload: dict[str, Any] = {}
    turn_error: list[str] = []
    done_sentinel = {"type": "_turn_done"}

    def _run_turn() -> None:
        try:
            service = soul._ensure_speak_service()
            result = service.run_turn(
                session_id,
                question,
                stream=True,
                mode="inbound",
                record=True,
            )
            turn_payload["result"] = _serialize_turn_result(result)
        except Exception as exc:
            turn_error.append(str(exc))
        finally:
            loop.call_soon_threadsafe(event_q.put_nowait, done_sentinel)

    worker = threading.Thread(target=_run_turn, name="webui-speak-turn", daemon=True)
    worker.start()

    aborted = False

    async def _receive_client() -> None:
        nonlocal aborted
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "abort" and msg.get("gen_id") == gen_id:
                aborted = True
                port.close()
                return

    receive_task = asyncio.create_task(_receive_client())

    try:
        while True:
            item = await event_q.get()
            if item is done_sentinel:
                break
            await websocket.send_json(item)
            if item.get("kind") == "finish":
                await asyncio.sleep(0)

        if turn_error:
            await websocket.send_json({"type": "error", "message": turn_error[0]})
        elif turn_payload:
            payload = turn_payload["result"]
            await websocket.send_json({
                "type": "finish",
                "gen_id": gen_id,
                "aborted": aborted,
                **payload,
            })
        else:
            await websocket.send_json({
                "type": "finish",
                "gen_id": gen_id,
                "aborted": aborted,
                "answer": "",
            })
    finally:
        receive_task.cancel()
        try:
            await receive_task
        except (asyncio.CancelledError, Exception):
            pass
        soul.bind_speak_stream_port(None)
        port.close()
        state.set_streaming(False)
        await websocket.close()
