from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from config.llm_core.config import LLMConfig
from config.react.memory.memory_config import MemoryConfig
from config.react.prompt_config import PromptConfig
from config.react.tao_config import TaoConfig
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.action.tools.weather import WeatherAction
from react.tao import ChunkEvent, FinishEvent, StepEvent, StepStartEvent, TaoLoop

app = FastAPI()

_llm: LLM | None = None
_tao_loop: TaoLoop | None = None
_llm_cfg: LLMConfig | None = None

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_LLM_CONFIG_YAML = os.path.join(_REPO_ROOT, "config", "llm_core", "config.yaml")


@app.on_event("startup")
def _startup():
    global _llm, _llm_cfg
    if not os.path.exists(_LLM_CONFIG_YAML):
        return
    cfg = LLMConfig.from_yaml(_LLM_CONFIG_YAML)
    if not cfg.model:
        return
    _llm_cfg = cfg
    _llm = LLM(cfg)
    print(f"[webui] LLM auto-loaded from config  model={cfg.model!r}")

_ALL_TOOLS: dict[str, tuple[type, str]] = {
    "weather": (WeatherAction, "查询指定城市的当前天气情况"),
}


class InitRequest(BaseModel):
    model: str
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 512
    temperature: float = 1.0
    do_sample: bool = False
    device: str = "auto"
    system_prompt: str = ""


class ChatRequest(BaseModel):
    prompt: str


class ReactInitRequest(BaseModel):
    lang: str = "cn"
    max_steps: int = 10
    tools: list[str] = ["weather"]


class ReactRunRequest(BaseModel):
    question: str


@app.get("/api/config")
def get_config():
    if _llm_cfg is None:
        return {}
    return {
        "model":         _llm_cfg.model,
        "api_key":       _llm_cfg.api_key,
        "base_url":      _llm_cfg.base_url or "",
        "max_tokens":    _llm_cfg.max_tokens,
        "temperature":   _llm_cfg.temperature,
        "do_sample":     _llm_cfg.do_sample,
        "device":        _llm_cfg.device,
        "system_prompt": _llm_cfg.system_prompt,
    }


@app.post("/api/init")
def init_llm(req: InitRequest):
    global _llm, _llm_cfg
    cfg = LLMConfig(
        model=req.model,
        api_key=req.api_key,
        base_url=req.base_url,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        do_sample=req.do_sample,
        device=req.device,
        system_prompt=req.system_prompt,
    )
    _llm_cfg = cfg
    _llm = LLM(cfg)
    mode = "api" if req.api_key else "local"
    return {"status": "ok", "mode": mode}


@app.post("/api/chat")
def chat(req: ChatRequest):
    if _llm is None:
        return JSONResponse(status_code=400, content={"error": "LLM not initialized. Call /api/init first."})

    def generate():
        for chunk in _llm.stream_generate(req.prompt):
            yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/react/init")
def react_init(req: ReactInitRequest):
    global _tao_loop
    if _llm is None:
        return JSONResponse(status_code=400, content={"error": "LLM 尚未初始化，请先调用 /api/init。"})

    executor = ActionExecutor()
    tool_descriptions: dict[str, str] = {}

    for name in req.tools:
        if name not in _ALL_TOOLS:
            return JSONResponse(status_code=400, content={"error": f"未知工具: {name!r}"})
        cls, desc = _ALL_TOOLS[name]
        executor.register(cls)
        tool_descriptions[name] = desc

    cfg = TaoConfig(
        max_steps=req.max_steps,
        prompt=PromptConfig(lang=req.lang),
        memory=MemoryConfig(),
    )
    _tao_loop = TaoLoop(llm=_llm, executor=executor, tool_descriptions=tool_descriptions, cfg=cfg)
    return {"status": "ok", "tools": req.tools, "lang": req.lang}


@app.post("/api/react/run")
def react_run(req: ReactRunRequest):
    if _tao_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct 尚未初始化，请先调用 /api/react/init。"})

    def generate():
        for event in _tao_loop.stream(req.question):
            if isinstance(event, StepStartEvent):
                data = {"type": "step_start", "index": event.index}
            elif isinstance(event, ChunkEvent):
                data = {"type": "chunk", "index": event.index, "chunk": event.chunk}
            elif isinstance(event, StepEvent):
                data = {
                    "type": "step",
                    "index": event.index,
                    "thought": event.thought,
                    "action": event.action,
                    "action_input": event.action_input,
                    "observation": event.observation,
                }
            elif isinstance(event, FinishEvent):
                data = {"type": "finish", "answer": event.answer}
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status")
def status():
    return {"initialized": _llm is not None, "react_ready": _tao_loop is not None}


@app.get("/api/react/tools")
def react_tools():
    return {"tools": {name: desc for name, (_, desc) in _ALL_TOOLS.items()}}


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()
