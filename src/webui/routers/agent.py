from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from agent.inbound import RouteContext, RouteKind
from agent.soul.speak.io.outbound.websocket import WebSocketSpeakStreamPort
from state import get_state
from webui.speak_pipeline_gate import pipeline_reject_reason
from webui.speak_typing_sim import SimulatedTypingStreamPort
from worker.work.types import WorkIntentSignal

from .soul import _soul_or_400

router = APIRouter()


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


@router.websocket("/ws/agent/run")
async def ws_agent_run(websocket: WebSocket) -> None:
    """Agent 顶层入站：首轮分类到 Speak 或 Worker；Speak WS 保持纯对话。"""
    state = get_state()
    await websocket.accept()
    unregister_ws = state.register_websocket(websocket)
    try:
        await _ws_agent_session(websocket, state)
    finally:
        unregister_ws()


async def _ws_agent_session(websocket: WebSocket, state) -> None:
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
    if not gen_id:
        await websocket.send_json({"type": "error", "message": "missing gen_id"})
        await websocket.close()
        return
    delivery_mode = str(first.get("delivery_mode", "stream")).strip().lower()
    if delivery_mode not in ("stream", "simulated"):
        delivery_mode = "stream"
    pipeline = str(first.get("pipeline", "request_driven")).strip() or "request_driven"
    # 接口收敛（single-stream 需求 R3 / 开放问题 2）：前端实连口与
    # /ws/speak/run 共用同一 pipeline 收敛门——唯一合法值 request_driven。
    reject = pipeline_reject_reason(pipeline)
    if reject:
        await websocket.send_json({"type": "error", "message": reject})
        await websocket.close()
        return

    soul, err = _soul_or_400()
    if err is not None or soul is None or not soul.is_running:
        await websocket.send_json({"type": "error", "message": "Soul unavailable"})
        await websocket.close()
        return
    # speak 默认沉睡：前端接入（session_open）即唤醒
    await asyncio.to_thread(soul.wake_speak)
    if state.inbound_router is None:
        await websocket.send_json({"type": "error", "message": "inbound router unavailable"})
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

    if state.speak_delivery_hub is None:
        from webui.speak_delivery_hub import WebUISpeakDeliveryHub

        state.speak_delivery_hub = WebUISpeakDeliveryHub()
    hub = state.speak_delivery_hub

    def _put_payload(payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(event_q.put_nowait, payload)

    def _put_work_payload(payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(event_q.put_nowait, payload)
        if payload.get("type") == "work_fallback_to_speak":
            question = str(payload.get("payload", {}).get("question", "")).strip()
            if question:
                loop.call_soon_threadsafe(
                    inbound_q.put_nowait,
                    {"type": "_agent_speak_fallback", "question": question},
                )

    unregister_hub = hub.register(
        session_id=session_id,
        channel_id=channel_id,
        gen_id=gen_id,
        port=port,
        put_payload=_put_payload,
    )
    soul.bind_speak_stream_port(hub)
    soul.start_dialogue_session(session_id)
    soul.align_speak_visitor(session_id, channel_id)
    if state.work_service is not None:
        state.work_service.bind_session_sink(session_id, _put_work_payload)

    client_gone = False
    session_route = ""
    first_route_work_id = ""

    async def _signal_client_gone() -> None:
        nonlocal client_gone
        if client_gone:
            return
        client_gone = True
        await inbound_q.put({"type": "close", "reason": "disconnect"})

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
        if client_gone:
            return False
        if (
            websocket.application_state != WebSocketState.CONNECTED
            or websocket.client_state != WebSocketState.CONNECTED
        ):
            await _signal_client_gone()
            return False
        async with send_lock:
            try:
                await websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
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

    async def _run_speak_turn(question: str, *, route_source: str = "") -> None:
        soul.speak_set_delivery_mode(delivery_mode)
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
                    fut.add_done_callback(lambda _f: loop.call_soon_threadsafe(turn_done.set))
                else:
                    loop.call_soon_threadsafe(turn_done.set)

        try:
            await _send_json({
                "type": "turn_start",
                "gen_id": gen_id,
                "question": question,
                "pipeline": pipeline,
                "route": RouteKind.speak.value,
                "route_source": route_source,
            })
            worker = threading.Thread(target=_run_turn, name="webui-agent-speak-turn", daemon=True)
            worker.start()
            await turn_done.wait()
            await asyncio.to_thread(worker.join)
            await event_q.join()
        finally:
            hub.end_client_turn(session_id)
        if turn_error:
            await _send_json({"type": "error", "message": turn_error[0]})
            return
        payload = turn_payload.get("result") or {"answer": ""}
        await _send_json({"type": "turn_finish", "gen_id": gen_id, **payload})

    async def _submit_work(question: str, *, source: str, work_id: str, confidence: float) -> None:
        if state.work_service is None:
            await _send_json({"type": "error", "message": "worker unavailable"})
            return
        signal = WorkIntentSignal(
            work_id=work_id,
            session_id=session_id,
            channel_id=channel_id,
            gen_id=gen_id,
            question=question,
            matched_terms=[source],
            reason="agent_inbound_route",
            confidence=confidence,
        )
        await asyncio.to_thread(state.work_service.submit_intent, signal)

    pump_task = asyncio.create_task(_pump_events())

    try:
        await _send_json({
            "type": "session_ready",
            "gen_id": gen_id,
            "session_id": session_id,
            "delivery_mode": delivery_mode,
            "pipeline": pipeline,
            "agent_route": True,
        })
        warm = soul.speak_is_live_warm(session_id)
        if not warm:
            soul.seed_session_warm_spread(session_id)
            await asyncio.to_thread(soul.arm_enter_greeting, session_id)
        else:
            await asyncio.to_thread(soul.speak_bootstrap_proactive_loop, session_id)

        while True:
            msg = await inbound_q.get()
            msg_type = str(msg.get("type", "user_message"))
            if msg_type == "close":
                break

            if msg_type == "typing_pulse":
                snap = await asyncio.to_thread(
                    soul.speak_on_typing_pulse,
                    session_id,
                    typing=bool(msg.get("typing", False)),
                    draft=str(msg.get("draft", "")),
                )
                await _send_json({"type": "typing_ack", "gen_id": gen_id, "session_id": session_id, "snapshot": snap})
                continue

            if msg_type == "set_typing_idle_ms":
                raw_ms = msg.get("typing_idle_ms", 3000)
                ms = int(raw_ms) if str(raw_ms).isdigit() else 3000
                idle_ms = await asyncio.to_thread(soul.speak_set_typing_idle_ms, session_id, ms=ms)
                await _send_json({"type": "typing_idle_ms", "gen_id": gen_id, "typing_idle_ms": idle_ms})
                continue

            if msg_type == "pipeline":
                # 会话中途切换 request_driven / direct：收敛门复检，非法值拒改不断连
                requested = str(msg.get("pipeline", "")).strip()
                reject = pipeline_reject_reason(requested)
                if reject:
                    await _send_json({"type": "error", "gen_id": gen_id, "message": reject})
                    continue
                pipeline = requested
                await _send_json(
                    {
                        "type": "pipeline",
                        "gen_id": gen_id,
                        "session_id": session_id,
                        "pipeline": pipeline,
                    }
                )
                continue

            if msg_type == "ping":
                await _send_json({"type": "pong", "gen_id": gen_id})
                continue

            if msg_type == "abort" and msg.get("gen_id") == gen_id:
                port.close()
                await _send_json({"type": "aborted", "gen_id": gen_id})
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
                await _send_json({"type": "proactive_ack_ok", "gen_id": gen_id, "delivery_id": did})
                continue

            if msg_type == "work_confirmation_response":
                work_id = str(msg.get("work_id", "")).strip()
                if work_id and state.work_service is not None:
                    await asyncio.to_thread(
                        state.work_service.handle_confirmation,
                        work_id,
                        approved=bool(msg.get("approved", False)),
                        reason=str(msg.get("reason", "")),
                        reason_code=str(msg.get("reason_code", "")),
                        soul=soul,
                    )
                continue

            if msg_type == "work_abort":
                work_id = str(msg.get("work_id", "")).strip()
                if work_id and state.work_service is not None:
                    await asyncio.to_thread(state.work_service.abort, work_id)
                continue

            if msg_type == "work_monitor_request":
                work_id = str(msg.get("work_id", "")).strip()
                if work_id and state.work_service is not None:
                    await asyncio.to_thread(state.work_service.monitor_snapshot, work_id)
                continue

            if msg_type == "route_pierce":
                true_route = str(msg.get("true_route", "")).strip()
                if true_route:
                    result = await asyncio.to_thread(
                        state.inbound_router.pierce,
                        session_id,
                        true_route,
                    )
                    session_route = result.true_route.value
                    await _send_json({
                        "type": "route_pierce_ok",
                        "gen_id": gen_id,
                        "session_id": session_id,
                        "route": result.true_route.value,
                        "previous_route": result.previous_route.value if result.previous_route else "",
                        "sample_id": result.sample_id,
                    })
                    if result.true_route == RouteKind.speak:
                        if first_route_work_id and state.work_service is not None:
                            await asyncio.to_thread(
                                state.work_service.abort,
                                first_route_work_id,
                                reason="路由击穿，改走对话",
                            )
                        await _run_speak_turn(result.question, route_source="route_pierce")
                    elif result.true_route == RouteKind.work:
                        first_route_work_id = f"{result.sample_id}:pierce"
                        await _submit_work(
                            result.question,
                            source="route_pierce",
                            work_id=first_route_work_id,
                            confidence=1.0,
                        )
                continue

            if msg_type == "_agent_speak_fallback":
                question = str(msg.get("question", "")).strip()
                if question:
                    await _run_speak_turn(question, route_source="work_fallback")
                continue

            if msg_type != "user_message":
                continue

            question = str(msg.get("question", "")).strip()
            if not question:
                await _send_json({"type": "error", "message": "empty question"})
                continue

            if not session_route:
                try:
                    decision = await asyncio.to_thread(
                        state.inbound_router.handle,
                        question,
                        RouteContext(
                            session_id=session_id,
                            channel_id=channel_id,
                            gen_id=gen_id,
                        ),
                    )
                except Exception as exc:
                    # 分类失败不得打断会话：降级为对话路由并告知客户端。
                    session_route = RouteKind.speak.value
                    await _send_json({
                        "type": "route_decision",
                        "route": "speak",
                        "session_id": session_id,
                        "sample_id": "",
                        "source": "fallback_error",
                        "confidence": 0.0,
                        "score": 0.0,
                        "meta": {"error": str(exc)[:200]},
                        "gen_id": gen_id,
                        "channel_id": channel_id,
                    })
                else:
                    session_route = decision.route.value
                    await _send_json({**decision.to_ws_dict(), "gen_id": gen_id, "channel_id": channel_id})
                    if decision.route == RouteKind.work:
                        first_route_work_id = decision.sample_id
                        await _submit_work(
                            question,
                            source=decision.source,
                            work_id=decision.sample_id,
                            confidence=decision.confidence,
                        )
                        continue

            if session_route == RouteKind.speak.value:
                await _run_speak_turn(question, route_source="sticky")
            else:
                await _send_json({
                    "type": "error",
                    "message": "worker follow-up is not wired yet; start a new request",
                })
    finally:
        detach_inbound()
        if state.work_service is not None:
            state.work_service.unbind_session_sink(session_id)
        if not receive_task.done():
            await inbound_q.put({"type": "close", "reason": "cleanup"})
            receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        unregister_hub()
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
