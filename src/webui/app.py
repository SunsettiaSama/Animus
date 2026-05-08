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

from routers import llm, react, memory, persona, scheduler, knowledge, voice, history, plan, benchmark, probe
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
    react.router,
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
]:
    app.include_router(_r)


@app.on_event("startup")
def _startup():
    state = get_state()
    state.main_event_loop = asyncio.get_event_loop()
    state.notify_queue = asyncio.Queue()

    def _make_scheduler_notify_fn(st):
        def _notify(task, answer: str) -> None:
            rt = task.reply_target
            if rt is None:
                return
            if rt.get("type") == "webui":
                if st.notify_queue is not None and st.main_event_loop is not None:
                    item = {"type": "scheduled_reply", "task_name": task.name, "answer": answer}
                    st.main_event_loop.call_soon_threadsafe(st.notify_queue.put_nowait, item)
            elif rt.get("type") == "bot":
                if st.bot_service is not None:
                    st.bot_service.send_scheduled_reply(rt, task.name, answer)
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

        # Create and start the global scheduler engine.
        # TemporalClock runs on its own daemon thread — no run_coroutine_threadsafe needed.
        from agent.scheduler import SchedulerEngine, SchedulerConfig, TimelineStore
        sch_cfg = SchedulerConfig(
            scheduler_dir=state.cache.scheduler_dir,
            llm_cfg_path=state.llm_config_yaml,
        )
        state.scheduler_engine = SchedulerEngine(
            sch_cfg,
            timeline=TimelineStore(state.cache.timeline_dir),
            notify_fn=_make_scheduler_notify_fn(state),
        )
        state.scheduler_engine.start()
        print("[webui] Global scheduler engine started (TemporalClock thread)")

        from routers.react import ReactInitRequest, _do_react_init
        state.react_init_event.clear()
        state.react_init_error = ""
        state.conv_loop = None
        _do_react_init(ReactInitRequest(), state)

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

    state.task_runner.submit("startup_init", _bg, on_error=_on_error)
    print("[webui] Background startup init submitted")


@app.on_event("shutdown")
def _shutdown():
    state = get_state()
    # Unblock any open SSE /api/plan/stream connections so they exit before
    # uvicorn forcefully cancels them (avoids CancelledError in the logs).
    state.plan_broadcast({"type": "done", "status": "shutdown", "answer": ""})
    if state.notify_queue is not None:
        state.notify_queue.put_nowait(None)
    if state.scheduler_engine is not None:
        state.scheduler_engine.stop()
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
