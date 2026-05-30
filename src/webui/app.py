from __future__ import annotations

import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# src/webui/ — for routers, state, schemas
sys.path.insert(0, _HERE)
# src/ — for config, react, llm_core, etc.
sys.path.insert(0, os.path.join(_HERE, ".."))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from agent.adapters.fastapi_react import create_react_router
from agent.adapters.fastapi_chat import create_chat_router
from routers import llm, memory, persona, scheduler, knowledge, voice, history, plan, benchmark, probe, soul, speak, accounts
from routers.infra import router as infra_router
from state import get_state

_HERE = os.path.dirname(__file__)

app = FastAPI(title="ReAct Agent")


@app.middleware("http")
async def _no_cache_js(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/js/") or request.url.path.startswith("/static/css/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.mount(
    "/static",
    StaticFiles(directory=os.path.join(_HERE, "static")),
    name="static",
)

for _r in [
    llm.router,
    create_react_router(get_state),
    create_chat_router(get_state),
    memory.router,
    persona.router,
    scheduler.router,
    knowledge.router,
    infra_router,
    voice.router,
    history.router,
    plan.router,
    benchmark.router,
    probe.router,
    soul.router,
    speak.router,
    accounts.router,
]:
    app.include_router(_r)


@app.on_event("startup")
def _startup():
    state = get_state()
    state.main_event_loop = asyncio.get_event_loop()
    state.notify_queue = asyncio.Queue()

    # ── ChannelRouter setup ───────────────────────────────────────────────────
    from infra.channel_router import ChannelRouter, ReplyTarget

    channel_router = ChannelRouter()
    state.channel_router = channel_router

    def _webui_deliver(target: ReplyTarget, title: str, message: str) -> None:
        if state.notify_queue is not None and state.main_event_loop is not None:
            item = {"type": "scheduled_reply", "task_name": title, "answer": message}
            state.main_event_loop.call_soon_threadsafe(state.notify_queue.put_nowait, item)

    def _bot_deliver(target: ReplyTarget, title: str, message: str) -> None:
        if state.bot_service is not None:
            rt_dict = target.to_task_dict()
            state.bot_service.send_scheduled_reply(rt_dict, title, message)

    channel_router.register("webui", _webui_deliver)
    channel_router.register("bot",   _bot_deliver)

    # ── Bark / ntfy notifiers ─────────────────────────────────────────────────
    from config.infra.bark_config import BarkConfig
    from config.infra.ntfy_config import NtfyConfig
    from infra.network.notify.bark import BarkNotifier
    from infra.network.notify.ntfy import NtfyNotifier

    bark_notifier = BarkNotifier(BarkConfig.load())
    ntfy_notifier = NtfyNotifier(NtfyConfig.load())
    state.bark_notifier = bark_notifier
    state.ntfy_notifier = ntfy_notifier

    def _bark_deliver(target: ReplyTarget, title: str, message: str) -> None:
        bark_notifier.send(title, message, device_key=target.params.get("device_key"))

    def _ntfy_deliver(target: ReplyTarget, title: str, message: str) -> None:
        ntfy_notifier.send(title, message, topic=target.params.get("topic"))

    channel_router.register("bark", _bark_deliver)
    channel_router.register("ntfy", _ntfy_deliver)

    def _make_scheduler_notify_fn(st):
        def _notify(task, answer: str) -> None:
            rt = task.reply_target
            if rt is None:
                # Fallback: pick the best available channel automatically.
                # Priority: bark → ntfy → webui
                if st.bark_notifier is not None and st.bark_notifier._cfg.enabled:
                    rt = {"type": "bark"}
                elif st.ntfy_notifier is not None and st.ntfy_notifier._cfg.enabled:
                    rt = {"type": "ntfy"}
                else:
                    rt = {"type": "webui"}
            target = ReplyTarget.from_task_dict(rt)
            if target is not None:
                st.channel_router.deliver(target, task.name, answer)
        return _notify

    def _bg() -> None:
        if not os.path.exists(state.llm_config_yaml):
            return
        from config.llm_core.config import LLMConfig
        cfg = LLMConfig.from_yaml(state.llm_config_yaml)
        if not cfg.model:
            return
        state.llm_service.start(cfg)
        print(f"[webui] LLM auto-loaded  model={cfg.model!r}")

        # Create and start the global scheduler engine via AgentService.
        from agent.service import AgentService
        from runtime.scheduler import SchedulerConfig, TimelineService, WorkJournal
        from config import paths as _paths
        import yaml as _yaml

        _sched_yaml = _paths.scheduler_config_yaml
        if _sched_yaml.exists():
            with open(_sched_yaml, encoding="utf-8") as _f:
                _sched_dict = _yaml.safe_load(_f) or {}
            _sched_dict.pop("scheduler_dir", None)
            sch_cfg = SchedulerConfig.from_dict({
                **_sched_dict,
                "scheduler_dir": state.cache.scheduler_dir,
                "llm_cfg_path": state.llm_config_yaml,
            })
        else:
            sch_cfg = SchedulerConfig(
                scheduler_dir=state.cache.scheduler_dir,
                llm_cfg_path=state.llm_config_yaml,
            )
        state.scheduler_config_yaml = str(_sched_yaml)

        _journal = WorkJournal(state.cache.history_dir)
        state.scheduler_journal = _journal

        _agent_service = AgentService(
            llm_cfg_path=state.llm_config_yaml,
            scheduler_cfg=sch_cfg,
            llm_service=state.llm_service,
            notify_fn=_make_scheduler_notify_fn(state),
            timeline=TimelineService(state.cache.timeline_dir),
            journal=_journal,
            channel_router=state.channel_router,
        )
        _agent_service.start()
        state.scheduler_engine = _agent_service.engine
        state.agent_service = _agent_service
        print("[webui] Global scheduler engine started via AgentService (TemporalClock thread)")

        from agent.adapters.react_bridge import do_react_init
        from agent.adapters.react_schemas import ReactInitRequest

        state.react_init_event.clear()
        state.react_init_error = ""
        state.conv_loop = None
        do_react_init(ReactInitRequest(), state)

        # Start bot service only when explicitly enabled by the user.
        # Runs independently of the browser — closing the WebUI frontend
        # does not affect it.
        if state.bot_service is not None:
            from config.infra.bot_config import BotConfig
            bot_cfg = BotConfig.load()
            if bot_cfg.enabled:
                state.main_event_loop.call_soon_threadsafe(
                    state.bot_service.start
                )
                print(f"[webui] BotService started  transport={bot_cfg.transport!r}")

    def _on_error(exc: BaseException) -> None:
        state.react_init_error = str(exc)
        state.react_init_event.set()
        print(f"[webui] Startup init error: {exc}")

    state.install_shutdown_signals()
    state.task_runner.submit("startup_init", _bg, on_error=_on_error)
    print("[webui] Background startup init submitted")


@app.on_event("shutdown")
def _shutdown():
    state = get_state()
    state.prepare_graceful_shutdown()
    if state.scheduler_engine is not None:
        state.scheduler_engine.stop()
    if state.session_manager is not None:
        state.session_manager.stop_all()
        state.session_manager = None
    state.task_runner.shutdown(wait=True, timeout=15)
    state.service_registry.stop_all()
    if state.active_tao is not None:
        state.active_tao.close()
        state.active_tao = None


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(_HERE, "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()
