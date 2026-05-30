from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel, Field

from agent.soul.speak.io.outbound.stream import SpeakStreamEvent
from state import get_state

from agent.soul.speak.session.prompt_trace import get_prompt_trace

from webui.speak_typing_sim import SimulatedTypingStreamPort

from .soul import _resolve_soul, _soul_or_400

router = APIRouter()

# 前端须在 localStorage 持久化 channel session_id，经 WS 传入；不再使用固定 webui。


class SpeakResetRequest(BaseModel):
    session_id: str = Field(default="")


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
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            {"type": "__port_closed__"},
        )

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
    silence_policy = result.meta.get("silence_policy")
    return {
        "session_id": result.session_id,
        "answer": result.answer,
        "session_state": result.meta.get("session_state", "finish"),
        "queued": bool(result.meta.get("queued", False)),
        "interrupt": bool(result.meta.get("interrupt", False)),
        "recorded": result.recorded,
        "notes": list(result.notes),
        "output": output,
        "silence_policy": silence_policy if isinstance(silence_policy, str) else None,
        "hide_agent": silence_policy == "hidden",
    }


def _submit_user_message(soul, session_id: str, text: str) -> dict[str, Any]:
    service = soul._ensure_speak_service()
    submit = service._session_manager.submit_user_input(
        session_id,
        text,
        stream=True,
        mode="inbound",
        record=True,
    )
    return {
        "queued": bool(submit.queued),
        "interrupt": bool(submit.interrupt),
        "notes": list(submit.notes),
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
        "session_id": "",
    }


class SpeakTraceRequest(BaseModel):
    session_id: str = Field(default="")
    enabled: bool = True


@router.get("/api/speak/session/{session_id}/trace")
def get_speak_session_trace(session_id: str):
    """trace 开关存于进程内全局表，不依赖 Soul 是否已 start。"""
    sid = session_id.strip()
    trace = get_prompt_trace()
    return {
        "session_id": sid,
        "enabled": trace.is_enabled(sid),
        "global": trace.global_enabled,
        "traced_sessions": trace.enabled_sessions(),
    }


@router.post("/api/speak/session/trace")
def set_speak_session_trace(body: SpeakTraceRequest):
    if not body.session_id.strip():
        return {"ok": False, "error": "missing session_id"}
    sid = body.session_id.strip()
    trace = get_prompt_trace()
    trace.set_session(sid, body.enabled)
    return {
        "ok": True,
        "session_id": sid,
        "enabled": trace.is_enabled(sid),
        "global": trace.global_enabled,
    }


@router.get("/api/speak/session/{session_id}/debug")
def get_speak_session_debug(session_id: str):
    sid = session_id.strip()
    trace = get_prompt_trace()
    payload: dict[str, Any] = {
        "trace": {
            "session_id": sid,
            "enabled": trace.is_enabled(sid),
            "global": trace.global_enabled,
            "traced_sessions": trace.enabled_sessions(),
        },
        "cache": None,
        "soul_ready": False,
        "module_trace_hint": (
            "开启 trace 后下一轮对话会在主进程 stdout 打印各模块原文；"
            "含 persona/status/memory/distiller/LLM system+user"
        ),
    }
    soul = _resolve_soul()
    if soul is None or not soul.is_running:
        payload["reason"] = "Soul 未运行，暂无 session 缓存（可先 start Soul 再发消息）"
        return payload
    speak = soul._ensure_speak_service()
    if speak is None:
        payload["reason"] = "Speak 未就绪"
        return payload
    payload["soul_ready"] = True
    payload["cache"] = speak.session_trace_cache(sid)
    return payload


@router.post("/api/speak/reset")
def reset_speak_session(body: SpeakResetRequest | None = None):
    soul, err = _soul_or_400()
    if err is not None:
        return err
    if body is None or not body.session_id.strip():
        return {"ok": False, "error": "missing session_id"}
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
    """Speak 双向会话：同一条 WebSocket 可多轮 user_message，流式事件持续下行。"""
    state = get_state()
    await websocket.accept()
    unregister_ws = state.register_websocket(websocket)
    try:
        return await _ws_speak_run_session(websocket, state)
    finally:
        unregister_ws()


async def _ws_speak_run_session(websocket: WebSocket, state) -> None:
    first = await websocket.receive_json()
    session_id = str(first.get("session_id", "")).strip()
    if not session_id:
        await websocket.send_json({"type": "error", "message": "missing session_id"})
        await websocket.close()
        return
    channel_id = str(first.get("channel_id", "")).strip() or session_id
    gen_id = str(first.get("gen_id", "")).strip()
    delivery_mode = str(first.get("delivery_mode", "stream")).strip().lower()
    if delivery_mode not in ("stream", "simulated"):
        delivery_mode = "stream"
    if not gen_id:
        await websocket.send_json({"type": "error", "message": "missing gen_id"})
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
    inbound_q: asyncio.Queue = asyncio.Queue()
    base_port = WebUISpeakStreamPort(loop, event_q, gen_id=gen_id)
    if delivery_mode == "simulated":
        port: WebUISpeakStreamPort | SimulatedTypingStreamPort = SimulatedTypingStreamPort(
            inner=base_port,
            loop=loop,
        )
    else:
        port = base_port
    soul.bind_speak_stream_port(port)
    soul.start_dialogue_session(session_id)
    soul.align_speak_visitor(session_id, channel_id)

    if first.get("type") in ("start", "user_message", None):
        question = str(first.get("question", "")).strip()
        if question:
            await inbound_q.put(first)

    async def _receive_client() -> None:
        while True:
            msg = await websocket.receive_json()
            await inbound_q.put(msg)

    receive_task = asyncio.create_task(_receive_client())

    async def _pump_events_until(done_sentinel: object) -> None:
        while True:
            item = await event_q.get()
            if item is done_sentinel:
                return
            if isinstance(item, dict) and item.get("type") == "__port_closed__":
                return
            await websocket.send_json(item)

    try:
        await websocket.send_json({
            "type": "session_ready",
            "gen_id": gen_id,
            "session_id": session_id,
            "delivery_mode": delivery_mode,
        })

        while True:
            msg = await inbound_q.get()
            msg_type = str(msg.get("type", "user_message"))

            if msg_type == "close":
                break

            msg_delivery = str(msg.get("delivery_mode", "")).strip().lower()
            if msg_delivery in ("stream", "simulated"):
                delivery_mode = msg_delivery
                if delivery_mode == "simulated" and not isinstance(port, SimulatedTypingStreamPort):
                    base_port = port if isinstance(port, WebUISpeakStreamPort) else port.inner
                    port = SimulatedTypingStreamPort(inner=base_port, loop=loop)
                elif delivery_mode == "stream" and isinstance(port, SimulatedTypingStreamPort):
                    port = port.inner
                soul.bind_speak_stream_port(port)

            if msg_type == "abort" and msg.get("gen_id") == gen_id:
                port.close()
                await websocket.send_json({"type": "aborted", "gen_id": gen_id})
                continue

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "gen_id": gen_id})
                continue

            if msg_type not in ("start", "user_message"):
                continue

            question = str(msg.get("question", "")).strip()
            if not question:
                await websocket.send_json({"type": "error", "message": "empty question"})
                continue

            if soul._ensure_speak_service().session_manager.is_pushing(session_id):
                ack = await asyncio.to_thread(
                    _submit_user_message,
                    soul,
                    session_id,
                    question,
                )
                await websocket.send_json({
                    "type": "user_ack",
                    "gen_id": gen_id,
                    "question": question,
                    **ack,
                })
                continue

            turn_payload: dict[str, Any] = {}
            turn_error: list[str] = []
            done_sentinel = object()

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
                    if isinstance(port, SimulatedTypingStreamPort):
                        fut = asyncio.run_coroutine_threadsafe(
                            port.flush_pending(session_id),
                            loop,
                        )

                        def _after_flush(_f) -> None:
                            loop.call_soon_threadsafe(event_q.put_nowait, done_sentinel)

                        fut.add_done_callback(_after_flush)
                    else:
                        loop.call_soon_threadsafe(event_q.put_nowait, done_sentinel)

            await websocket.send_json({
                "type": "turn_start",
                "gen_id": gen_id,
                "question": question,
            })

            worker = threading.Thread(target=_run_turn, name="webui-speak-turn", daemon=True)
            worker.start()

            pump_task = asyncio.create_task(_pump_events_until(done_sentinel))
            await pump_task
            if state.shutting_down:
                worker.join(timeout=2.0)
            else:
                worker.join()

            if turn_error:
                await websocket.send_json({"type": "error", "message": turn_error[0]})
                continue

            if turn_payload:
                payload = turn_payload["result"]
                await websocket.send_json({
                    "type": "turn_finish",
                    "gen_id": gen_id,
                    **payload,
                })
            else:
                await websocket.send_json({
                    "type": "turn_finish",
                    "gen_id": gen_id,
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
        if not state.shutting_down:
            await websocket.send_json({"type": "session_end", "gen_id": gen_id})
            await websocket.close()
