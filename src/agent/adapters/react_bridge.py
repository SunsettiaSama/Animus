from __future__ import annotations

from typing import Any, Callable


def push_notify(state: Any, task: str, message: str, done: bool = False) -> None:
    if state.notify_queue is None or state.main_event_loop is None:
        return
    item = {"type": "notify", "task": task, "message": message, "done": done}
    state.main_event_loop.call_soon_threadsafe(state.notify_queue.put_nowait, item)


def do_react_init(req: Any, state: Any) -> None:
    """在后台线程中构建 ConvLoop，注册到 SessionManager 的 webui 会话。"""
    from agent.react.factory import build_conv_loop
    from agent.session import SessionManager
    from agent.adapters.webui_bridge import WEBUI_SESSION_ID

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

    if getattr(state, "agent_service", None) is not None:
        soul = getattr(tl, "_soul", None)
        if soul is not None:
            state.agent_service.set_soul_service(soul)

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
