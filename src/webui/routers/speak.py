from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from fastapi import APIRouter, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect, WebSocketState

from agent.soul.speak.io.outbound.websocket import WebSocketSpeakStreamPort
from state import get_state

from agent.soul.speak.responders.request_driven.orchestrator.prompt_trace import get_prompt_trace

from webui.speak_typing_sim import SimulatedTypingStreamPort

from .soul import _resolve_soul, _soul_or_400

router = APIRouter()


class SpeakResetRequest(BaseModel):
    session_id: str = Field(default="")


class SpeakPageEnterRequest(BaseModel):
    session_id: str = Field(default="")
    page_key: str = Field(default="")
    messages: list[dict[str, Any]] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)


class SpeakCreateUiRequest(BaseModel):
    delivery_id: str = Field(default="")
    accepted: bool = True
    channel_id: str = Field(default="")
    session_id: str = Field(default="")


class SpeakProactiveAckRequest(BaseModel):
    delivery_id: str = Field(default="")
    channel_id: str = Field(default="")
    session_id: str = Field(default="")


def _serialize_turn_result(result) -> dict[str, Any]:
    from datetime import datetime, timezone

    output = result.output.to_dict() if result.output is not None else {}
    silence_policy = result.meta.get("silence_policy")
    pipeline = result.meta.get("pipeline")
    stream_events = []
    for event in getattr(result, "stream_events", None) or []:
        stream_events.append(
            {
                "kind": getattr(event, "kind", ""),
                "text": getattr(event, "text", "") or "",
                "final": bool(getattr(event, "final", False)),
                "meta": dict(getattr(event, "meta", None) or {}),
            }
        )
    meta = dict(result.meta)
    created_at = str(meta.get("created_at") or "").strip()
    if not created_at:
        created_at = datetime.now(timezone.utc).isoformat()
        meta["created_at"] = created_at
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
        "meta": meta,
        "silence_policy": silence_policy if isinstance(silence_policy, str) else None,
        "hide_agent": silence_policy == "hidden",
        "speak_events": stream_events,
        "created_at": created_at,
    }


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
    """兼容旧端点：不再人为轮转生命线，只恢复同一 session。"""
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
    opened = soul.start_dialogue_session(sid)
    return {
        "ok": True,
        "session_id": sid,
        "ended": None,
        "opened": opened,
        "reason": "session_reused",
    }


@router.post("/api/speak/page_enter")
def speak_page_enter(body: SpeakPageEnterRequest):
    """切到历史页：临时记忆注入 speak 生命线 buffer（最多两代）。"""
    sid = body.session_id.strip()
    page_key = body.page_key.strip() or "page"
    if not sid:
        return {"ok": False, "error": "missing session_id"}
    soul = _resolve_soul()
    if soul is None:
        return {"ok": False, "session_id": sid, "reason": "soul_unavailable"}
    return soul.speak_enter_page_context(
        sid,
        page_key=page_key,
        messages=list(body.messages or []),
        lines=list(body.lines or []),
    )


@router.post("/api/speak/create_ui")
def speak_create_ui(body: SpeakCreateUiRequest):
    """前端对 create_ui_request 的自动回执。"""
    did = body.delivery_id.strip()
    if not did:
        return {"ok": False, "error": "missing delivery_id"}
    soul = _resolve_soul()
    if soul is None:
        return {"ok": False, "reason": "soul_unavailable"}
    return soul.speak_resolve_create_ui(
        did,
        accepted=bool(body.accepted),
        channel_id=body.channel_id.strip(),
        session_id=body.session_id.strip(),
    )


@router.post("/api/speak/proactive_ack")
def speak_proactive_ack(body: SpeakProactiveAckRequest):
    """HTTP 备用 ACK；主路径走 WS proactive_ack。"""
    did = body.delivery_id.strip()
    if not did:
        return {"ok": False, "error": "missing delivery_id"}
    soul = _resolve_soul()
    if soul is None:
        return {"ok": False, "reason": "soul_unavailable"}
    ok = soul.speak_acknowledge_proactive(
        did,
        session_id=body.session_id.strip(),
        channel_id=body.channel_id.strip(),
    )
    return {"ok": ok, "delivery_id": did}


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
    if str(first.get("type", "")).strip() != "session_open":
        await websocket.send_json({"type": "error", "message": "expected session_open"})
        await websocket.close()
        return
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
    # 接口收敛（single-stream 需求 R3 / 开放问题 2）：对话对外唯一 pipeline。
    if pipeline != "request_driven":
        await websocket.send_json({
            "type": "error",
            "message": f"unsupported pipeline: {pipeline!r} (only request_driven)",
        })
        await websocket.close()
        return
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
    detach_inbound = state.attach_speak_inbound_queue(inbound_q)
    send_lock = asyncio.Lock()
    base_port = WebSocketSpeakStreamPort(loop, event_q, gen_id=gen_id)
    if delivery_mode == "simulated":
        port: WebSocketSpeakStreamPort | SimulatedTypingStreamPort = SimulatedTypingStreamPort(
            inner=base_port,
            loop=loop,
        )
    else:
        port = base_port

    # ?? speak?enter_greeting / character handoff???? hub ???
    # turn_start/turn_finish??????? stream ctrl?speak_event ???????
    if state.speak_delivery_hub is None:
        from webui.speak_delivery_hub import WebUISpeakDeliveryHub

        state.speak_delivery_hub = WebUISpeakDeliveryHub()
    hub = state.speak_delivery_hub

    def _put_hub_payload(payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(event_q.put_nowait, payload)

    unregister_hub = hub.register(
        session_id=session_id,
        channel_id=channel_id,
        gen_id=gen_id,
        port=port,
        put_payload=_put_hub_payload,
    )
    soul.bind_speak_stream_port(hub)
    soul.start_dialogue_session(session_id)
    soul.align_speak_visitor(session_id, channel_id)

    _CLOSE_SENTINEL = {"type": "close", "reason": "disconnect"}
    client_gone = False

    async def _signal_client_gone() -> None:
        nonlocal client_gone
        if client_gone:
            return
        client_gone = True
        await inbound_q.put(dict(_CLOSE_SENTINEL))

    async def _receive_client() -> None:
        while True:
            if state.shutting_down:
                await _signal_client_gone()
                return
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                await _signal_client_gone()
                return
            await inbound_q.put(msg)

    receive_task = asyncio.create_task(_receive_client())

    async def _send_json(payload: dict[str, Any]) -> bool:
        """发送 JSON；客户端已断开时静默返回 False，并触发会话收尾。"""
        if client_gone:
            return False
        if (
            websocket.application_state != WebSocketState.CONNECTED
            or websocket.client_state != WebSocketState.CONNECTED
        ):
            await _signal_client_gone()
            return False
        async with send_lock:
            if client_gone:
                return False
            if (
                websocket.application_state != WebSocketState.CONNECTED
                or websocket.client_state != WebSocketState.CONNECTED
            ):
                await _signal_client_gone()
                return False
            try:
                await websocket.send_json(payload)
            except WebSocketDisconnect:
                await _signal_client_gone()
                return False
            except RuntimeError:
                # send after close / ASGI already torn down
                await _signal_client_gone()
                return False
        return True

    async def _pump_events() -> None:
        while True:
            item = await event_q.get()
            if isinstance(item, dict) and item.get("type") == "__port_closed__":
                event_q.task_done()
                return
            ok = await _send_json(item)
            event_q.task_done()
            if not ok:
                return

    pump_task = asyncio.create_task(_pump_events())

    try:
        await _send_json({
            "type": "session_ready",
            "gen_id": gen_id,
            "session_id": session_id,
            "delivery_mode": delivery_mode,
            "pipeline": pipeline,
        })
        warm = soul.speak_is_live_warm(session_id)
        if not warm:
            soul.seed_session_warm_spread(session_id)
            # 进房初始化勿堵 asyncio 事件循环（编剧 Agent 多步 LLM 可达数秒）
            await asyncio.to_thread(soul.arm_enter_greeting, session_id)
        else:
            # 热生命线重连：仍要挂回 poll 扫描，否则主动性静默丢失
            await asyncio.to_thread(soul.speak_bootstrap_proactive_loop, session_id)
            # 大纲开头若上次因无 live 未投，重连后补推（后台，不堵收消息）
            await asyncio.to_thread(soul.ensure_screenwriter_init, session_id)

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
                hub.update_port(session_id, channel_id, port)
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

            if msg_type == "proactive_ack":
                did = str(msg.get("delivery_id", "")).strip()
                if did:
                    await asyncio.to_thread(
                        soul.speak_acknowledge_proactive,
                        did,
                        session_id=session_id,
                        channel_id=channel_id,
                    )
                await _send_json({
                    "type": "proactive_ack_ok",
                    "gen_id": gen_id,
                    "delivery_id": did,
                })
                continue

            if msg_type != "user_message":
                continue

            soul.speak_set_delivery_mode(delivery_mode)

            question = str(msg.get("question", "")).strip()
            if not question:
                await _send_json({"type": "error", "message": "empty question"})
                continue

            # 真实用户输入优先于连接后延迟触发的主动问候。
            # 忙碌时也直接跑 turn：run_turn 会打断出站并把原文交给角色（已有剧情卡）。
            soul.cancel_enter_greeting(session_id)

            turn_payload: dict[str, Any] = {}
            turn_error: list[str] = []
            turn_done = asyncio.Event()
            hub.begin_client_turn(session_id)

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

            try:
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
            finally:
                hub.end_client_turn(session_id)

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
        detach_inbound()
        if not receive_task.done():
            await inbound_q.put({"type": "close", "reason": "cleanup"})
            receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        unregister_hub()
        # ?? hub ????? proactive ????????? None
        soul.bind_speak_stream_port(hub)
        soul.cancel_enter_greeting(session_id)
        port.close()
        if not pump_task.done():
            await event_q.put({"type": "__port_closed__"})
            pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass
        state.set_streaming(False)
        if (
            not state.shutting_down
            and websocket.application_state == WebSocketState.CONNECTED
            and websocket.client_state == WebSocketState.CONNECTED
        ):
            await _send_json({"type": "session_end", "gen_id": gen_id})
            await websocket.close()
