from __future__ import annotations

import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# src/webui/ — for routers, state, schemas
sys.path.insert(0, _HERE)
# src/ — for config, react, llm_core, etc.
sys.path.insert(0, os.path.join(_HERE, ".."))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from routers import llm, react, memory, persona, scheduler, knowledge, voice, history, plan, benchmark, probe
from routers.infra import router as infra_router
from state import get_state

_HERE = os.path.dirname(__file__)

app = FastAPI(title="ReAct Agent")
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

    def _bg() -> None:
        if not os.path.exists(state.llm_config_yaml):
            return
        from config.llm_core.config import LLMConfig
        cfg = LLMConfig.from_yaml(state.llm_config_yaml)
        if not cfg.model:
            return
        state.llm_service.start(cfg)
        print(f"[webui] LLM auto-loaded  model={cfg.model!r}")

        from routers.react import ReactInitRequest, _do_react_init
        state.react_init_event.clear()
        state.react_init_error = ""
        state.conv_loop = None
        _do_react_init(ReactInitRequest(), state)

        # Start bot service if a WS URL is configured.  Runs independently of
        # the browser — closing the WebUI frontend does not affect it.
        if state.bot_service is not None:
            from config.infra.bot_config import BotConfig
            bot_cfg = BotConfig.load()
            if bot_cfg.ws_url:
                state.main_event_loop.call_soon_threadsafe(
                    state.bot_service.start
                )
                print(f"[webui] BotService started  url={bot_cfg.ws_url!r}")

    def _on_error(exc: BaseException) -> None:
        state.react_init_error = str(exc)
        state.react_init_event.set()
        print(f"[webui] Startup init error: {exc}")

    state.task_runner.submit("startup_init", _bg, on_error=_on_error)
    print("[webui] Background startup init submitted")


@app.on_event("shutdown")
def _shutdown():
    state = get_state()
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
