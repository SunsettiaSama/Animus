from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config.llm_core.config import LLMConfig
from llm_core.llm import LLM

app = FastAPI()

_llm: LLM | None = None


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


@app.post("/api/init")
def init_llm(req: InitRequest):
    global _llm
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
    _llm = LLM(cfg)
    mode = "api" if req.api_key else "local"
    return {"status": "ok", "mode": mode}


@app.post("/api/chat")
def chat(req: ChatRequest):
    if _llm is None:
        return JSONResponse(status_code=400, content={"error": "LLM not initialized. Call /api/init first."})
    result = _llm.generate(req.prompt)
    return {"response": result}


@app.get("/api/status")
def status():
    return {"initialized": _llm is not None}


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()
