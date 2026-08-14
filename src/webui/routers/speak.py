from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from fastapi import APIRouter, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.soul.speak.io.outbound.websocket import WebSocketSpeakStreamPort
from state import get_state

from agent.soul.speak.responders.request_driven.orchestrator.prompt_trace import get_prompt_trace

from webui.speak_typing_sim import SimulatedTypingStreamPort

from .soul import _resolve_soul, _soul_or_400

router = APIRouter()


class SpeakResetRequest(BaseModel):
    session_id: str = Field(default="")


def _serialize_turn_result(result) -> dict[str, Any]:
    output = result.output.to_dict() if result.output is not None else {}
    silence_policy = result.meta.get("silence_policy")
    pipeline = result.meta.get("pipeline")
    return {
        "session_id": result.session_id,
        "answer": result.answer,
        "session_state": result.meta.get("session_state", "finish"),
        "pipeline": pipeline if isinstance(pipeline, str) else None,
        "queued": bool(result.meta.get("queued", False)),
        "interrupt": bool(result.meta.get("interrupt", False)),
        "recorded": result.recorded,
        "notes": list(result.notes),
        "output": output,
        "meta": dict(result.meta),
        "silence_policy": silence_policy if isinstance(silence_policy, str) else None,
        "hide_agent": silence_policy == "hidden",
    }


def _submit_user_message(
    soul,
    session_id: str,
    text: str,
    *,
    responder: str | None = None,
) -> dict[str, Any]:
    return soul.speak_submit_user_input(
        session_id,
        text,
        stream=True,
        mode="inbound",
        record=True,
        responder=responder,
    )


@router.get("/api/speak/status")
def get_speak_status():
    soul = _resolve_soul()
    if soul is None:
        return {"status": "unavailable", "ready": False, "reason": "Soul ????"}
    running = soul.is_running
    speak_ready = running and soul.speak_initialized
    return {
        "status": "ready" if speak_ready else "idle",
        "ready": speak_ready,
        "soul_state": soul.state,
        "session_id": "",
    }


@router.get("/api/speak/notify")
async def speak_notify_stream(channel_id: str = "") -> StreamingResponse:
    """Notify SSE?? channel ????????????????"""
    state = get_state()
    queue: asyncio.Queue = asyncio.Queue()
    detach = state.attach_notify_subscriber(channel_id.strip(), queue)

    async def _generate():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    async def _stream():
        try:
            async for chunk in _generate():
                yield chunk
        finally:
            detach()

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class SpeakTraceRequest(BaseModel):
    session_id: str = Field(default="")
    enabled: bool = True


@router.get("/api/speak/session/{session_id}/trace")
def get_speak_session_trace(session_id: str):
    """trace ?????????????? Soul ??? start?"""
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
            "?? trace ??????????? stdout ????????"
            "? persona/status/memory/distiller/LLM system+user"
        ),
    }
    soul = _resolve_soul()
    if soul is None or not soul.is_running:
        payload["reason"] = "Soul ?????? session ????? start Soul ?????"
        return payload
    if not soul.speak_initialized:
        payload["reason"] = "Speak ???"
        return payload
    payload["soul_ready"] = True
    payload["cache"] = soul.speak_session_trace_cache(sid)
    return payload


@router.post("/api/speak/reset")
def reset_speak_session(
    body: SpeakResetRequest | None = None,
    session_id: str = "",
):
    sid = session_id.strip()
    if body is not None and body.session_id.strip():
        sid = body.session_id.strip()
    if not sid:
        return {"ok": False, "error": "missing session_id"}
    soul = _resolve_soul()
    if soul is None:
        return {
            "ok": False,
            "session_id": sid,
            "reason": "soul_unavailable",
            "ended": None,
        }
    ended = soul.finalize_speak_session(sid)
    return {
        "ok": True,
        "session_id": sid,
        "ended": ended,
    }


@router.websocket("/ws/speak/run")
async def ws_speak_run(websocket: WebSocket) -> None:
    """Speak ???????? WebSocket ??? user_message??????????"""
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
    pipeline = str(first.get("pipeline", "request_driven")).strip() or "request_driven"
    if not gen_id:
        await websocket.send_json({"type": "error", "message": "missing gen_id"})
        await websocket.close()
        return

    soul, err = _soul_or_400()
    if err is not None:
        await websocket.send_json({"type": "error", "message": "Soul ???"})
        await websocket.close()
        return

    if not soul.is_running:
        await websocket.send_json({"type": "error", "message": "Soul ???"})
        await websocket.close()
        return

    if not state.try_start_streaming(gen_id):
        await websocket.send_json({"type": "error", "message": "Already streaming."})
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    event_q: asyncio.Queue = asyncio.Queue()
    inbound_q: asyncio.Queue = asyncio.Queue()
    send_lock = asyncio.Lock()
    base_port = WebSocketSpeakStreamPort(loop, event_q, gen_id=gen_id)
    if delivery_mode == "simulated":
        port: WebSocketSpeakStreamPort | SimulatedTypingStreamPort = SimulatedTypingStreamPort(
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

    async def _send_json(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def _pump_events() -> None:
        while True:
            item = await event_q.get()
            if isinstance(item, dict) and item.get("type") == "__port_closed__":
                event_q.task_done()
                return
            await _send_json(item)
            event_q.task_done()

    pump_task = asyncio.create_task(_pump_events())

    try:
        await _send_json({
            "type": "session_ready",
            "gen_id": gen_id,
            "session_id": session_id,
            "delivery_mode": delivery_mode,
            "pipeline": pipeline,
        })
        soul.seed_session_warm_spread(session_id)
        soul.arm_enter_greeting(session_id)

        while True:
            msg = await inbound_q.get()
            msg_type = str(msg.get("type", "user_message"))

            if msg_type == "close":
                break

            msg_delivery = str(msg.get("delivery_mode", "")).strip().lower()
            if msg_delivery in ("stream", "simulated"):
                delivery_mode = msg_delivery
                if delivery_mode == "simulated" and not isinstance(port, SimulatedTypingStreamPort):
                    base_port = port if isinstance(port, WebSocketSpeakStreamPort) else port.inner
                    port = SimulatedTypingStreamPort(inner=base_port, loop=loop)
                elif delivery_mode == "stream" and isinstance(port, SimulatedTypingStreamPort):
                    port = port.inner
                soul.bind_speak_stream_port(port)
                soul.speak_set_delivery_mode(delivery_mode)

            msg_pipeline = str(msg.get("pipeline", "")).strip()
            if msg_pipeline:
                pipeline = msg_pipeline

            if msg_type == "typing_pulse":
                typing = bool(msg.get("typing", False))
                draft = str(msg.get("draft", ""))
                snap = await asyncio.to_thread(
                    soul.speak_on_typing_pulse,
                    session_id,
                    typing=typing,
                    draft=draft,
                )
                await _send_json({
                    "type": "typing_ack",
                    "gen_id": gen_id,
                    "session_id": session_id,
                    "snapshot": snap,
                })
                continue

            if msg_type == "set_typing_idle_ms":
                raw_ms = msg.get("typing_idle_ms", 3000)
                ms = int(raw_ms) if str(raw_ms).isdigit() else 3000
                idle_ms = await asyncio.to_thread(
                    soul.speak_set_typing_idle_ms,
                    session_id,
                    ms=ms,
                )
                await _send_json({
                    "type": "typing_idle_ms",
                    "gen_id": gen_id,
                    "typing_idle_ms": idle_ms,
                })
                continue

            if msg_type == "abort" and msg.get("gen_id") == gen_id:
                port.close()
                await _send_json({"type": "aborted", "gen_id": gen_id})
                continue

            if msg_type == "ping":
                await _send_json({"type": "pong", "gen_id": gen_id})
                continue

            if msg_type not in ("start", "user_message"):
                continue

            soul.speak_set_delivery_mode(delivery_mode)

            question = str(msg.get("question", "")).strip()
            if not question:
                await _send_json({"type": "error", "message": "empty question"})
                continue

            if soul.speak_is_pushing(session_id):
                ack = await asyncio.to_thread(
                    _submit_user_message,
                    soul,
                    session_id,
                    question,
                    responder=pipeline,
                )
                await _send_json({
                    "type": "user_ack",
                    "gen_id": gen_id,
                    "question": question,
                    "pipeline": pipeline,
                    **ack,
                })
                continue

            turn_payload: dict[str, Any] = {}
            turn_error: list[str] = []
            turn_done = asyncio.Event()

            def _run_turn() -> None:
                try:
                    result = soul.speak_run_turn(
                        session_id,
                        question,
                        stream=True,
                        mode="inbound",
                        record=True,
                        responder=pipeline,
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
                            loop.call_soon_threadsafe(turn_done.set)

                        fut.add_done_callback(_after_flush)
                    else:
                        loop.call_soon_threadsafe(turn_done.set)

            await _send_json({
                "type": "turn_start",
                "gen_id": gen_id,
                "question": question,
                "pipeline": pipeline,
            })

            worker = threading.Thread(target=_run_turn, name="webui-speak-turn", daemon=True)
            worker.start()

            await turn_done.wait()
            if state.shutting_down:
                await asyncio.to_thread(worker.join, 2.0)
            else:
                await asyncio.to_thread(worker.join)
            await event_q.join()

            if turn_error:
                await _send_json({"type": "error", "message": turn_error[0]})
                continue

            if turn_payload:
                payload = turn_payload["result"]
                await _send_json({
                    "type": "turn_finish",
                    "gen_id": gen_id,
                    **payload,
                })
            else:
                await _send_json({
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
        soul.cancel_enter_greeting(session_id)
        port.close()
        pump_task.cancel()
        try:
            await pump_task
        except (asyncio.CancelledError, Exception):
            pass
        state.set_streaming(False)
        if not state.shutting_down:
            await _send_json({"type": "session_end", "gen_id": gen_id})
            await websocket.close()
