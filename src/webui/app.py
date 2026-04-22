from __future__ import annotations

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config.llm_core.config import LLMConfig
from config.react.memory.memory_config import MemoryConfig
from config.react.persona_config import PersonaConfig
from config.react.prompt_config import PromptConfig
from config.react.tao_config import TaoConfig
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.action.manager import ToolManager
from react.loop import ConvLoop
from react.tao import ChunkEvent, FinishEvent, PromptPreviewEvent, StepEvent, StepStartEvent, TaoLoop

app = FastAPI()

_llm: LLM | None = None
_conv_loop: ConvLoop | None = None
_llm_cfg: LLMConfig | None = None
_tool_manager = ToolManager()

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_LLM_CONFIG_YAML = os.path.join(_REPO_ROOT, "config", "llm_core", "config.yaml")
_HISTORY_DIR = os.path.join(_REPO_ROOT, ".react")
_PERSONA_DIR = os.path.join(_REPO_ROOT, ".react", "persona")
_PERSONA_CFG_FILE = os.path.join(_PERSONA_DIR, "persona_config.json")


@app.on_event("startup")
def _startup():
    global _llm, _llm_cfg
    if not os.path.exists(_LLM_CONFIG_YAML):
        return
    cfg = LLMConfig.from_yaml(_LLM_CONFIG_YAML)
    _llm_cfg = cfg  # always store config, even if model is empty
    if not cfg.model:
        return
    _llm = LLM(cfg)
    print(f"[webui] LLM auto-loaded  model={cfg.model!r}")


# ── Request models ────────────────────────────────────────────────────────────

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
    primary_tools: list[str] | None = None


class ReactRunRequest(BaseModel):
    question: str


class SaveConfigRequest(BaseModel):
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 512
    temperature: float = 1.0
    do_sample: bool = False
    device: str = "auto"
    system_prompt: str = ""


class PersonaSaveRequest(BaseModel):
    enabled: bool = False
    chronicle_enabled: bool = True
    name: str = "Assistant"
    background: str = ""
    traits: list[str] = []
    values: list[str] = []
    style: str = ""
    chronicle_recent_in_prompt: int = 5
    max_chronicle_entries: int = 100
    max_profile_chars: int = 500
    max_chronicle_entry_chars: int = 200
    max_chronicle_render_chars: int = 800


class SaveConvRequest(BaseModel):
    id: str
    title: str
    mode: str
    messages: list
    created_at: str
    updated_at: str


class RestoreRequest(BaseModel):
    messages: list[dict]


# ── Persona helpers ───────────────────────────────────────────────────────────

def _load_persona_cfg_dict() -> dict:
    if not os.path.exists(_PERSONA_CFG_FILE):
        return {}
    with open(_PERSONA_CFG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_persona_config() -> PersonaConfig:
    d = _load_persona_cfg_dict()
    return PersonaConfig(
        enabled=d.get("enabled", False),
        persona_dir=_PERSONA_DIR,
        max_chronicle_entries=d.get("max_chronicle_entries", 100),
        chronicle_recent_in_prompt=d.get("chronicle_recent_in_prompt", 5),
        chronicle_enabled=d.get("chronicle_enabled", True),
        max_profile_chars=d.get("max_profile_chars", 500),
        max_chronicle_entry_chars=d.get("max_chronicle_entry_chars", 200),
        max_chronicle_render_chars=d.get("max_chronicle_render_chars", 800),
    )


# ── Config ────────────────────────────────────────────────────────────────────

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


@app.post("/api/config/save")
def save_config(req: SaveConfigRequest):
    import yaml
    os.makedirs(os.path.dirname(_LLM_CONFIG_YAML), exist_ok=True)
    data = {
        "model":         req.model,
        "api_key":       req.api_key,
        "base_url":      req.base_url or "",
        "max_tokens":    req.max_tokens,
        "temperature":   req.temperature,
        "do_sample":     req.do_sample,
        "device":        req.device,
        "system_prompt": req.system_prompt or "",
    }
    with open(_LLM_CONFIG_YAML, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    return {"status": "ok"}


# ── LLM ───────────────────────────────────────────────────────────────────────

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
    return {"status": "ok", "mode": "api" if req.api_key else "local"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    if _llm is None:
        return JSONResponse(status_code=400, content={"error": "LLM not initialized."})

    def generate():
        for chunk in _llm.stream_generate(req.prompt):
            yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── ReAct ─────────────────────────────────────────────────────────────────────

@app.post("/api/react/init")
def react_init(req: ReactInitRequest):
    global _conv_loop
    if _llm is None:
        return JSONResponse(status_code=400, content={"error": "LLM not initialized."})

    if req.primary_tools is not None:
        unknown = [n for n in req.primary_tools if n not in _tool_manager.registry]
        if unknown:
            return JSONResponse(status_code=400, content={"error": f"Unknown tools: {unknown}"})

    executor = _tool_manager.build_executor()
    tool_descriptions = _tool_manager.primary_descriptions(req.primary_tools)

    cfg = TaoConfig(
        max_steps=req.max_steps,
        prompt=PromptConfig(lang=req.lang),
        memory=MemoryConfig(),
        persona=_load_persona_config(),
    )
    tao = TaoLoop(llm=_llm, executor=executor, tool_descriptions=tool_descriptions, cfg=cfg)
    _conv_loop = ConvLoop(tao)
    return {
        "status": "ok",
        "primary_tools": list(tool_descriptions.keys()),
        "total_tools": len(_tool_manager.registry),
        "lang": req.lang,
    }


@app.post("/api/react/restore")
def react_restore(req: RestoreRequest):
    """Restore PromptManager history from a saved conversation's message list."""
    if _conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
    _conv_loop.restore(req.messages)
    return {"status": "ok", "turn_count": _conv_loop.turn_count}


@app.post("/api/react/reset")
def react_reset():
    if _conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
    _conv_loop.reset()
    return {"status": "ok"}


@app.post("/api/react/run")
def react_run(req: ReactRunRequest):
    if _conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})

    def generate():
        for event in _conv_loop.stream(req.question):
            if isinstance(event, PromptPreviewEvent):
                data = {"type": "prompt_preview", "messages": event.messages}
            elif isinstance(event, StepStartEvent):
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
        # Commit and rebuild static cache after all SSE events are flushed.
        _conv_loop.post_process()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status")
def status():
    turn_count = _conv_loop.turn_count if _conv_loop is not None else 0
    return {
        "initialized": _llm is not None,
        "react_ready": _conv_loop is not None,
        "turn_count": turn_count,
    }


@app.get("/api/react/tools")
def react_tools():
    by_category: dict[str, list[dict]] = {}
    for info in _tool_manager.all_tool_info():
        by_category.setdefault(info["category"], []).append(info)
    return {
        "total": len(_tool_manager.registry),
        "primary": _tool_manager.primary_names,
        "by_category": by_category,
    }


@app.get("/api/react/tools/search")
def react_tools_search(query: str, top_k: int = 5):
    results = _tool_manager.search(query, top_k)
    return {
        "query": query,
        "results": [
            {"name": m.name, "description": m.description, "category": m.category}
            for m in results
        ],
    }


# ── Persona ───────────────────────────────────────────────────────────────────

@app.get("/api/persona")
def get_persona():
    from react.persona.store import PersonaStore
    store = PersonaStore(_PERSONA_DIR)
    profile = store.load_profile()
    d = _load_persona_cfg_dict()
    return {
        "enabled":                   d.get("enabled", False),
        "chronicle_enabled":         d.get("chronicle_enabled", True),
        "profile":                   profile.to_dict(),
        "chronicle_recent_in_prompt": d.get("chronicle_recent_in_prompt", 5),
        "max_chronicle_entries":     d.get("max_chronicle_entries", 100),
        "max_profile_chars":         d.get("max_profile_chars", 500),
        "max_chronicle_entry_chars": d.get("max_chronicle_entry_chars", 200),
        "max_chronicle_render_chars": d.get("max_chronicle_render_chars", 800),
    }


@app.post("/api/persona/save")
def save_persona(req: PersonaSaveRequest):
    from react.persona.profile import PersonaProfile
    from react.persona.store import PersonaStore
    os.makedirs(_PERSONA_DIR, exist_ok=True)
    store = PersonaStore(_PERSONA_DIR)
    store.save_profile(PersonaProfile(
        name=req.name,
        background=req.background,
        traits=req.traits,
        values=req.values,
        style=req.style,
    ))
    cfg_data = {
        "enabled":                   req.enabled,
        "chronicle_enabled":         req.chronicle_enabled,
        "chronicle_recent_in_prompt": req.chronicle_recent_in_prompt,
        "max_chronicle_entries":     req.max_chronicle_entries,
        "max_profile_chars":         req.max_profile_chars,
        "max_chronicle_entry_chars": req.max_chronicle_entry_chars,
        "max_chronicle_render_chars": req.max_chronicle_render_chars,
    }
    with open(_PERSONA_CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg_data, f, ensure_ascii=False, indent=2)
    return {"status": "ok"}


@app.get("/api/persona/chronicle")
def get_persona_chronicle():
    from react.persona.store import PersonaStore
    d = _load_persona_cfg_dict()
    store = PersonaStore(_PERSONA_DIR)
    chronicle = store.load_chronicle(d.get("max_chronicle_entries", 100))
    return {"entries": chronicle.to_dict().get("entries", [])}


# ── Conversation history ───────────────────────────────────────────────────────

@app.get("/api/history")
def list_history():
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    convs = []
    for fn in sorted(os.listdir(_HISTORY_DIR), reverse=True):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(_HISTORY_DIR, fn)
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        convs.append({
            "id":         c.get("id", fn[:-5]),
            "title":      c.get("title", "Untitled"),
            "mode":       c.get("mode", "chat"),
            "updated_at": c.get("updated_at", ""),
        })
    return {"conversations": convs}


@app.get("/api/history/{conv_id}")
def get_history_item(conv_id: str):
    path = os.path.join(_HISTORY_DIR, f"{conv_id}.json")
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "Not found"})
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/history")
def save_history_item(req: SaveConvRequest):
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    path = os.path.join(_HISTORY_DIR, f"{req.id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(req.dict(), f, ensure_ascii=False, indent=2)
    return {"status": "ok"}


@app.delete("/api/history/{conv_id}")
def delete_history_item(conv_id: str):
    path = os.path.join(_HISTORY_DIR, f"{conv_id}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "ok"}


# ── WebSocket streaming ────────────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_json()
    prompt  = data.get("prompt", "")
    history = data.get("history", [])   # [{role, content}, ...] prior turns

    if _llm is None:
        await websocket.send_json({"error": "LLM not initialized."})
        await websocket.close()
        return

    # Build a proper message list so multi-turn context is preserved.
    messages = []
    if _llm_cfg and _llm_cfg.system_prompt:
        messages.append(SystemMessage(content=_llm_cfg.system_prompt))
    for h in history:
        role = h.get("role", "")
        content = h.get("content", "").strip()
        if not content:
            continue
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=prompt))

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _produce():
        for chunk in _llm.stream_generate_messages(messages):
            loop.call_soon_threadsafe(queue.put_nowait, chunk)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(ThreadPoolExecutor(max_workers=1), _produce)

    while True:
        item = await queue.get()
        if item is None:
            break
        await websocket.send_json({"chunk": item})

    await websocket.send_json({"done": True})
    await websocket.close()


@app.websocket("/ws/react/run")
async def ws_react_run(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_json()
    question = data.get("question", "")

    if _conv_loop is None:
        await websocket.send_json({"error": "ReAct not initialized."})
        await websocket.close()
        return

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _produce():
        for event in _conv_loop.stream(question):
            if isinstance(event, PromptPreviewEvent):
                msg = {"type": "prompt_preview", "messages": event.messages}
            elif isinstance(event, StepStartEvent):
                msg = {"type": "step_start", "index": event.index}
            elif isinstance(event, ChunkEvent):
                msg = {"type": "chunk", "index": event.index, "chunk": event.chunk}
            elif isinstance(event, StepEvent):
                msg = {
                    "type": "step",
                    "index": event.index,
                    "thought": event.thought,
                    "action": event.action,
                    "action_input": event.action_input,
                    "observation": event.observation,
                }
            elif isinstance(event, FinishEvent):
                msg = {"type": "finish", "answer": event.answer}
            else:
                continue
            loop.call_soon_threadsafe(queue.put_nowait, msg)
        # Signal the consumer to close the WebSocket BEFORE post-processing.
        # The client receives the finish event and the connection is released
        # immediately; commit / embedding / cache-rebuild happen in the background.
        loop.call_soon_threadsafe(queue.put_nowait, None)

    def _on_produce_done(fut):
        exc = fut.exception()
        if exc:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "error", "message": str(exc)}
            )
            loop.call_soon_threadsafe(queue.put_nowait, None)

    task = loop.run_in_executor(ThreadPoolExecutor(max_workers=1), _produce)
    task.add_done_callback(_on_produce_done)

    while True:
        item = await queue.get()
        if item is None:
            break
        await websocket.send_json(item)

    # Run commit + static-cache rebuild in a background thread so the WebSocket
    # can close without waiting for embedding / disk writes / LLM distillation.
    # Mark the returned future's exception as retrieved to suppress asyncio warnings.
    post_fut = loop.run_in_executor(None, _conv_loop.post_process)
    post_fut.add_done_callback(lambda f: f.exception())

    await websocket.close()


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()
