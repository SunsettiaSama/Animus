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

from routers import llm, react, memory, persona, scheduler, knowledge, voice, history, plan
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
]:
    app.include_router(_r)


@app.on_event("startup")
def _startup():
    from config.llm_core.config import LLMConfig
    from llm_core.llm import LLM
    state = get_state()
    state.main_event_loop = asyncio.get_event_loop()
    if not os.path.exists(state.llm_config_yaml):
        return
    cfg = LLMConfig.from_yaml(state.llm_config_yaml)
    state.llm_cfg = cfg
    if not cfg.model:
        return
    state.llm = LLM(cfg)
    print(f"[webui] LLM auto-loaded  model={cfg.model!r}")


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
