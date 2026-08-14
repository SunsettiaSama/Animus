from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

from agent.soul.speak.io.outbound.notify import (
    make_notify_event,
    make_proactive_available_event,
)

logger = logging.getLogger(__name__)

_SPEAK_CONTEXT = re.compile(
    r"<speak context>(.*?)</speak context>",
    re.DOTALL | re.IGNORECASE,
)


def first_spoken_line(text: str) -> str:
    """角色对外第一句：优先 speak context，否则第一行/第一句。"""
    raw = text.strip()
    if not raw:
        return ""
    blocks = [block.strip() for block in _SPEAK_CONTEXT.findall(raw) if block.strip()]
    if blocks:
        raw = blocks[0]
    newline = raw.find("\n")
    if newline >= 0:
        line = raw[:newline].strip()
        raw = line if line else raw[newline + 1:].strip()
    best = -1
    best_sep = ""
    for sep in ("。", "！", "？", ".", "!", "?"):
        idx = raw.find(sep)
        if idx < 0:
            continue
        if best < 0 or idx < best:
            best = idx
            best_sep = sep
    if best >= 0:
        head = raw[:best].strip()
        if head:
            return head + best_sep
    return raw


def push_notify(state: Any, task: str, message: str, done: bool = False) -> None:
    if state.main_event_loop is None:
        return
    state.publish_notify(make_notify_event(task=task, message=message, done=done))


def _persist_proactive_history(state: Any, payload: dict) -> None:
    history_dir = str(getattr(state, "history_dir", "") or "").strip()
    if not history_dir:
        return
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return
    message = str(payload.get("message", "")).strip()
    spoken = first_spoken_line(message)
    now = datetime.now(timezone.utc).isoformat()
    title = spoken or str(payload.get("banner", "")).strip() or "Agent 主动通信"
    if len(title) > 48:
        title = title[:48] + "…"
    os.makedirs(history_dir, exist_ok=True)
    conv = {
        "id": session_id,
        "title": title,
        "mode": "conversation",
        "messages": [
            {
                "role": "assistant",
                "content": message,
                "agent_initiated": True,
                "proactive_intent_id": str(payload.get("proactive_intent_id", "")).strip(),
                "created_at": now,
            }
        ] if message else [],
        "work_items": [],
        "session_id": session_id,
        "channel_id": str(payload.get("channel_id", "")).strip(),
        "agent_initiated": True,
        "proactive_unread": True,
        "created_at": now,
        "updated_at": now,
    }
    path = os.path.join(history_dir, f"{session_id}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(conv, handle, ensure_ascii=False, indent=2)


def _notify_proactive_bark(state: Any, payload: dict) -> None:
    notifier = getattr(state, "bark_notifier", None)
    if notifier is None:
        return
    spoken = first_spoken_line(str(payload.get("message", "") or ""))
    if not spoken:
        return
    title = str(
        payload.get("agent_display_name")
        or payload.get("banner")
        or "栖灵"
    ).strip().replace("【", "").replace("】", "").replace("发来一条通信", "").strip("° ")
    if not title:
        title = "栖灵"
    notifier.send(title, spoken)


def queue_agent_proactive_session(state: Any, payload: dict) -> None:
    """Queue visible content for Speak WS, persist unread history, and notify Bark/SSE."""
    hub = state.speak_delivery_hub
    if hub is None:
        raise RuntimeError("WebUI Speak delivery hub is not ready")
    _persist_proactive_history(state, payload)
    _notify_proactive_bark(state, payload)
    delivered = hub.enqueue_proactive(payload)
    if delivered:
        return
    if state.main_event_loop is None:
        logger.warning("[speak_notify] proactive queued without notify stream")
        return
    item = make_proactive_available_event(
        session_id=str(payload.get("session_id", "") or ""),
        channel_id=str(payload.get("channel_id", "") or ""),
        proactive_intent_id=str(payload.get("proactive_intent_id", "") or ""),
        delivery_id=str(payload.get("delivery_id", "") or ""),
        source=str(payload.get("source", "") or ""),
        wait_reply=bool(payload.get("wait_reply", False)),
        online=bool(delivered),
    )
    logger.info(
        "[speak_notify] proactive available session_id=%s channel_id=%s source=%s",
        item.get("session_id"),
        item.get("channel_id"),
        item.get("source"),
    )
    state.publish_notify(item)


def wire_soul_agent_initiated_notify(soul: Any, state: Any) -> None:
    if soul is None:
        return
    if state.speak_delivery_hub is None:
        from webui.speak_delivery_hub import WebUISpeakDeliveryHub

        state.speak_delivery_hub = WebUISpeakDeliveryHub()
    soul.bind_speak_stream_port(state.speak_delivery_hub)
    if state.speak_notify_soul is soul:
        return
    soul.register_agent_initiated_handler(
        lambda payload: queue_agent_proactive_session(state, payload),
    )
    state.speak_notify_soul = soul


def do_react_init(req: Any, state: Any) -> None:
    """Legacy: build ConvLoop for optional ReAct tools / benchmark.

    WebUI primary boot uses ``do_soul_init`` instead. Prefer Soul/Speak.
    """
    from agent.adapters.soul_bootstrap import warn_legacy_react
    from agent.react.factory import build_conv_loop
    from agent.session import SessionManager
    from agent.adapters.webui_bridge import WEBUI_SESSION_ID

    warn_legacy_react("do_react_init")

    # 初始化 SessionManager（首次）
    if state.session_manager is None:
        state.session_manager = SessionManager()

    # 关闭旧 TaoLoop（如有）
    old_preload = state.preload_future
    old_tao = state.active_tao
    if old_preload is not None and not old_preload.done():
        old_preload.result(timeout=120)
    if old_tao is not None:
        old_tao.close()

    conv_loop = build_conv_loop(
        state,
        lang=req.lang,
        max_steps=req.max_steps,
        primary_tools=req.primary_tools,
        enable_kb=req.enable_kb,
        reply_target={"type": "webui"},
    )

    tl = conv_loop.tao_loop
    # backward-compat refs（scheduler 路由、benchmark 等仍通过这两个字段访问）
    state.active_tao = tl
    state.conv_loop = conv_loop

    soul = getattr(tl, "_soul", None)
    if soul is not None:
        # Do not overwrite an already-running Soul-first instance.
        if getattr(state, "soul_service", None) is None:
            state.soul_service = soul
        if getattr(state, "agent_service", None) is not None:
            state.agent_service.set_soul_service(
                state.soul_service if state.soul_service is not None else soul
            )
            wire_soul_agent_initiated_notify(
                state.soul_service if state.soul_service is not None else soul,
                state,
            )

    def _notify(task: str, message: str, done: bool) -> None:
        push_notify(state, task, message, done)

    state.session_manager.create_session(
        WEBUI_SESSION_ID,
        conv_loop,
        notify_fn=_notify,
    )

    # Plan 事件 fan-out（flow/plan 类事件广播到所有订阅的 WebSocket）
    def _make_plan_sink(st: Any) -> Callable[[dict], None]:
        from agent.adapters.react_wire import envelope_workflow_event

        def _sink(event_dict: dict) -> None:
            lp = st.main_event_loop
            if lp is None:
                return

            def _deliver() -> None:
                st.plan_broadcast(event_dict)
                wf = envelope_workflow_event(event_dict)
                for q in list(getattr(st, "reactive_ws_flow_queues", ())):
                    q.put_nowait(wf)

            lp.call_soon_threadsafe(_deliver)

        return _sink

    conv_loop.set_plan_event_sink(_make_plan_sink(state))
    state.react_init_event.set()

    def _preload_with_notify() -> None:
        push_notify(state, "preload", "正在加载嵌入模型与长期记忆…", done=False)
        conv_loop.preload()
        push_notify(state, "preload", "嵌入模型与长期记忆已就绪", done=True)

    state.preload_future = state.task_runner.submit("preload", _preload_with_notify)


def submit_post_process_with_notify(conv_loop: Any, state: Any) -> None:
    """保留供外部直接调用（如 /api/react/run SSE 端点），会话模式下已由 Session worker 自动处理。"""
    def _work() -> None:
        push_notify(state, "post_process", "正在写入记忆…", done=False)
        conv_loop.post_process()
        push_notify(state, "post_process", "记忆写入完成", done=True)

    state.task_runner.submit("post_process", _work)
