from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from storage.config import StorageConfig
from config import paths
from config.knowledge.config import KnowledgeConfig
from config.llm_core.config import LLMConfig
from config.react.memory.memory_config import MemoryConfig
from config.react.persona_config import PersonaConfig
from config.react.prompt_config import PromptConfig
from config.react.tao_config import TaoConfig
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.action.manager import ToolManager
from react.loop import ConvLoop
from react.memory.processor import MemoryProcessor
from react.tao import ChunkEvent, FinishEvent, PromptPreviewEvent, RetryEvent, StepEvent, StepStartEvent, TaoLoop
from react.prompt.template import get_template as _get_prompt_template

app = FastAPI()

_llm: LLM | None = None
_conv_loop: ConvLoop | None = None
_llm_cfg: LLMConfig | None = None
_tool_manager = ToolManager()
_prompt_lang: str = "cn"          # tracks language chosen at react_init time

_kb = None                        # KnowledgeBase | None, lazy-initialized
_kb_cfg: KnowledgeConfig = KnowledgeConfig()

_tts_engine = None                # TTSEngine | None, lazy-initialized
_stt_engine = None                # STTEngine | None, lazy-initialized

# Background initialisation state for TaoLoop (memory loading can be slow).
_react_init_event: threading.Event = threading.Event()
_react_init_event.set()           # initially in a "ready / idle" state
_react_init_error: str = ""

_LLM_CONFIG_YAML    = str(paths.llm_config_yaml)
_MEMORY_CONFIG_YAML = str(paths.memory_config_yaml)
_CACHE              = StorageConfig(root=str(paths.cache_root))
_HISTORY_DIR        = _CACHE.history_dir
_PERSONA_DIR        = _CACHE.persona_dir
_PERSONA_CFG_FILE   = os.path.join(_PERSONA_DIR, "persona_config.json")


def _load_memory_config() -> MemoryConfig:
    if os.path.exists(_MEMORY_CONFIG_YAML):
        return MemoryConfig.from_yaml(_MEMORY_CONFIG_YAML)
    return MemoryConfig()


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
    enable_kb: bool = False


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


class MemorySaveRequest(BaseModel):
    # L1 短期记忆
    st_enabled: bool = True
    st_max_turns: int = 10
    st_max_tokens: int = 2048
    st_distill_enabled: bool = True
    st_distill_trigger_steps: int = 4
    st_max_distillate_tokens: int = 400
    # L2 中期记忆（近期历史）
    mt_enabled: bool = True
    mt_window_days: int = 7
    mt_max_entries: int = 30
    mt_max_chars: int = 3000
    mt_consolidate_enabled: bool = True
    mt_consolidate_batch: int = 10
    mt_consolidate_interval_days: int = 1
    mt_max_consolidate_tokens: int = 500
    # L3 长期记忆
    lt_enabled: bool = False
    lt_top_k: int = 5
    lt_max_recall_chars: int = 3000
    lt_consolidation_k: int = 0
    lt_distill_enabled: bool = False
    lt_max_distill_tokens: int = 400
    # 里程碑
    ms_enabled: bool = False
    ms_max_milestones: int = 50
    ms_importance_threshold: float = 0.6
    ms_top_k_retrieve: int = 2
    ms_inject_detail: bool = True


class PersonaSaveRequest(BaseModel):
    enabled: bool = False
    name: str = "Assistant"
    background: str = ""
    traits: list[str] = []
    values: list[str] = []
    style: str = ""
    max_profile_chars: int = 500
    # 演化引擎
    evolution_enabled: bool = False
    evolve_interval: int = 1
    # 技能库
    skills_enabled: bool = True
    max_skills_in_prompt: int = 5
    max_skills_chars: int = 600
    # 自省
    reflection_enabled: bool = False
    reflect_interval: int = 3
    max_reflection_chars: int = 400


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
        max_profile_chars=d.get("max_profile_chars", 500),
        evolution_enabled=d.get("evolution_enabled", False),
        evolve_interval=d.get("evolve_interval", 1),
        skills_enabled=d.get("skills_enabled", True),
        max_skills_in_prompt=d.get("max_skills_in_prompt", 5),
        max_skills_chars=d.get("max_skills_chars", 600),
        reflection_enabled=d.get("reflection_enabled", False),
        reflect_interval=d.get("reflect_interval", 3),
        max_reflection_chars=d.get("max_reflection_chars", 400),
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


# ── Memory config ─────────────────────────────────────────────────────────────

@app.get("/api/memory")
def get_memory_config():
    cfg = _load_memory_config()
    return {
        "short_term": {
            "enabled":               cfg.short_term.enabled,
            "max_turns":             cfg.short_term.max_turns,
            "max_tokens":            cfg.short_term.max_tokens,
            "distill_enabled":       cfg.short_term.distill_enabled,
            "distill_trigger_steps": cfg.short_term.distill_trigger_steps,
            "max_distillate_tokens": cfg.short_term.max_distillate_tokens,
        },
        "medium_term": {
            "enabled":                   cfg.medium_term.enabled,
            "window_days":               cfg.medium_term.window_days,
            "max_entries":               cfg.medium_term.max_entries,
            "max_chars":                 cfg.medium_term.max_chars,
            "consolidate_enabled":       cfg.medium_term.consolidate_enabled,
            "consolidate_batch":         cfg.medium_term.consolidate_batch,
            "consolidate_interval_days": cfg.medium_term.consolidate_interval_days,
            "max_consolidate_tokens":    cfg.medium_term.max_consolidate_tokens,
        },
        "long_term": {
            "enabled":            cfg.long_term.enabled,
            "top_k":              cfg.long_term.top_k,
            "max_recall_chars":   cfg.long_term.max_recall_chars,
            "consolidation_k":    cfg.long_term.consolidation_k,
            "distill_enabled":    cfg.long_term.distill_enabled,
            "max_distill_tokens": cfg.long_term.max_distill_tokens,
        },
        "milestone": {
            "enabled":               cfg.milestone.enabled,
            "max_milestones":        cfg.milestone.max_milestones,
            "importance_threshold":  cfg.milestone.importance_threshold,
            "top_k_retrieve":        cfg.milestone.top_k_retrieve,
            "inject_detail":         cfg.milestone.inject_detail,
        },
    }


@app.post("/api/memory/save")
def save_memory_config(req: MemorySaveRequest):
    import yaml
    path = _MEMORY_CONFIG_YAML
    existing: dict = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    existing["short_term"] = {
        **existing.get("short_term", {}),
        "enabled":               req.st_enabled,
        "max_turns":             req.st_max_turns,
        "max_tokens":            req.st_max_tokens,
        "distill_enabled":       req.st_distill_enabled,
        "distill_trigger_steps": req.st_distill_trigger_steps,
        "max_distillate_tokens": req.st_max_distillate_tokens,
    }
    existing["medium_term"] = {
        **existing.get("medium_term", {}),
        "enabled":                   req.mt_enabled,
        "window_days":               req.mt_window_days,
        "max_entries":               req.mt_max_entries,
        "max_chars":                 req.mt_max_chars,
        "consolidate_enabled":       req.mt_consolidate_enabled,
        "consolidate_batch":         req.mt_consolidate_batch,
        "consolidate_interval_days": req.mt_consolidate_interval_days,
        "max_consolidate_tokens":    req.mt_max_consolidate_tokens,
    }
    existing["long_term"] = {
        **existing.get("long_term", {}),
        "enabled":            req.lt_enabled,
        "top_k":              req.lt_top_k,
        "max_recall_chars":   req.lt_max_recall_chars,
        "consolidation_k":    req.lt_consolidation_k,
        "distill_enabled":    req.lt_distill_enabled,
        "max_distill_tokens": req.lt_max_distill_tokens,
    }
    existing["milestone"] = {
        **existing.get("milestone", {}),
        "enabled":              req.ms_enabled,
        "max_milestones":       req.ms_max_milestones,
        "importance_threshold": req.ms_importance_threshold,
        "top_k_retrieve":       req.ms_top_k_retrieve,
        "inject_detail":        req.ms_inject_detail,
    }

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
    return {"status": "ok"}


@app.post("/api/memory/consolidate")
def consolidate_medium_term():
    """强制整合中期记忆（忽略每日节流限制）。供 WebUI「立即整理」按钮调用。"""
    if _conv_loop is None:
        return JSONResponse({"status": "error", "detail": "No active session."}, status_code=400)
    medium = getattr(_conv_loop._tao, "_medium_term", None)
    if medium is None:
        return JSONResponse({"status": "error", "detail": "Medium-term memory not enabled."}, status_code=400)
    did = medium.consolidate(force=True)
    if did:
        return {"status": "ok", "message": "Consolidation completed."}
    return {"status": "ok", "message": "Nothing to consolidate (too few entries or LLM not available)."}

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
    # Keep every LLM sub-component in the active TaoLoop in sync so that
    # persona evolution, milestone scoring, and generation all use the new
    # model/key immediately — without requiring a full react_init rebuild.
    if _conv_loop is not None:
        _conv_loop._tao.update_llm(_llm)
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
    global _conv_loop, _prompt_lang, _react_init_event, _react_init_error
    if _llm is None:
        return JSONResponse(status_code=400, content={"error": "LLM not initialized."})

    if req.primary_tools is not None:
        unknown = [n for n in req.primary_tools if n not in _tool_manager.registry]
        if unknown:
            return JSONResponse(status_code=400, content={"error": f"Unknown tools: {unknown}"})

    _prompt_lang = req.lang
    executor = _tool_manager.build_executor()
    tool_descriptions = _tool_manager.primary_descriptions(req.primary_tools)

    cfg = TaoConfig(
        max_steps=req.max_steps,
        storage=_CACHE,
        prompt=PromptConfig(lang=req.lang),
        memory=_load_memory_config(),
        persona=_load_persona_config(),
        knowledge=_kb_cfg if req.enable_kb else None,
    )

    category_summary = _tool_manager.category_summary()

    # Reset state and spin up a background thread so the heavy memory-loading
    # (embedding model + FAISS index) does not block the HTTP response.
    _react_init_event.clear()
    _react_init_error = ""
    _conv_loop = None

    def _do_init():
        global _conv_loop, _react_init_error
        tao = None
        try:
            tao = TaoLoop(
                llm=_llm,
                executor=executor,
                tool_descriptions=tool_descriptions,
                cfg=cfg,
                tool_category_summary=category_summary,
            )
            _conv_loop = ConvLoop(tao)
        except Exception as exc:
            _react_init_error = str(exc)
        finally:
            _react_init_event.set()
        if tao is not None:
            threading.Thread(target=tao.preload, daemon=True).start()

    threading.Thread(target=_do_init, daemon=True).start()
    return {"status": "initializing"}


@app.get("/api/react/status")
def react_status():
    if not _react_init_event.is_set():
        return {"status": "initializing"}
    if _react_init_error:
        return {"status": "error", "detail": _react_init_error}
    return {"status": "ready"}


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


@app.post("/api/react/memory/clear")
def react_memory_clear():
    """Wipe all persistent memory tiers and reset in-memory state."""
    if _conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
    _conv_loop._tao.clear_memory()
    return {"status": "ok", "message": "所有记忆已清空。"}


@app.post("/api/react/persona/clear")
def react_persona_clear():
    """Delete persona drift files (profile/skills/reflection/preference) and reset state."""
    if _conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
    if _conv_loop._tao._persona is None:
        return JSONResponse(status_code=400, content={"error": "Persona not enabled."})
    _conv_loop._tao.clear_persona()
    return {"status": "ok", "message": "人格漂移数据已清空。"}


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
    from react.persona.profile.store import ProfileStore
    store = ProfileStore(_PERSONA_DIR)
    profile = store.load_profile()
    d = _load_persona_cfg_dict()
    return {
        "enabled":           d.get("enabled", False),
        "profile":           profile.to_dict(),
        "max_profile_chars": d.get("max_profile_chars", 500),
        "evolution_enabled": d.get("evolution_enabled", False),
        "evolve_interval":   d.get("evolve_interval", 1),
        "skills_enabled":    d.get("skills_enabled", True),
        "max_skills_in_prompt": d.get("max_skills_in_prompt", 5),
        "max_skills_chars":  d.get("max_skills_chars", 600),
        "reflection_enabled": d.get("reflection_enabled", False),
        "reflect_interval":  d.get("reflect_interval", 3),
        "max_reflection_chars": d.get("max_reflection_chars", 400),
    }


@app.post("/api/persona/save")
def save_persona(req: PersonaSaveRequest):
    from react.persona.profile.profile import PersonaProfile
    from react.persona.profile.store import ProfileStore
    os.makedirs(_PERSONA_DIR, exist_ok=True)
    store = ProfileStore(_PERSONA_DIR)
    store.save_profile(PersonaProfile(
        name=req.name,
        background=req.background,
        traits=req.traits,
        values=req.values,
        style=req.style,
    ))
    cfg_data = {
        "enabled":              req.enabled,
        "max_profile_chars":    req.max_profile_chars,
        "evolution_enabled":    req.evolution_enabled,
        "evolve_interval":      req.evolve_interval,
        "skills_enabled":       req.skills_enabled,
        "max_skills_in_prompt": req.max_skills_in_prompt,
        "max_skills_chars":     req.max_skills_chars,
        "reflection_enabled":   req.reflection_enabled,
        "reflect_interval":     req.reflect_interval,
        "max_reflection_chars": req.max_reflection_chars,
    }
    with open(_PERSONA_CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg_data, f, ensure_ascii=False, indent=2)
    return {"status": "ok"}


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


@app.delete("/api/history")
def clear_all_history():
    if not os.path.exists(_HISTORY_DIR):
        return {"status": "ok", "deleted": 0}
    count = 0
    for fn in os.listdir(_HISTORY_DIR):
        if fn.endswith(".json"):
            os.remove(os.path.join(_HISTORY_DIR, fn))
            count += 1
    return {"status": "ok", "deleted": count}


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

    # Prepend a structured role block so the model knows the conversation's purpose.
    _tpl = _get_prompt_template(_prompt_lang)
    role_text = _tpl.chat_role.render(
        content=_llm_cfg.system_prompt.strip() if _llm_cfg and _llm_cfg.system_prompt else "",
        separator=_tpl.separator,
    )
    if role_text:
        messages.append(SystemMessage(content=role_text))
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
            elif isinstance(event, RetryEvent):
                msg = {"type": "retry", "index": event.index, "reason": event.reason}
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


# ── Knowledge Base API ────────────────────────────────────────────────────────

class KBIngestRequest(BaseModel):
    text: str
    title: str = ""
    domain: str = ""
    concept: str = ""


def _get_kb():
    global _kb
    if _kb is None:
        from knowledge import KnowledgeBase
        _kb = KnowledgeBase.from_config(_kb_cfg)
        _kb.setup()
    return _kb


@app.get("/api/kb/documents")
def kb_list_documents():
    kb = _get_kb()
    docs = kb.store.list_documents(include_deleted=False)
    return {
        "documents": [
            {
                "id":          d.id,
                "source":      d.source,
                "source_type": d.source_type,
                "title":       d.title or "",
                "status":      d.status,
                "meta":        d.meta or {},
                "created_at":  str(d.created_at),
            }
            for d in docs
        ]
    }


@app.get("/api/kb/search")
def kb_search(q: str, top_k: int = 5, top_k_each: int = 3, mode: str = "hybrid"):
    kb = _get_kb()
    if mode == "keyword":
        results = kb.search_keyword(q, top_k=top_k)
    elif mode == "semantic":
        results = kb.search_semantic(q, top_k=top_k)
    else:
        results = kb.hybrid_search(q, top_k_each=top_k_each)
    return {
        "query":  q,
        "mode":   mode,
        "results": [
            {
                "chunk_id": r.chunk_id,
                "doc_id":   r.doc_id,
                "score":    r.score,
                "source":   r.source,
                "content":  r.content,
                "meta":     r.meta,
            }
            for r in results
        ],
    }


@app.post("/api/kb/ingest")
def kb_ingest(req: KBIngestRequest):
    kb = _get_kb()
    meta: dict = {}
    if req.domain:
        meta["domain"] = req.domain
    if req.concept:
        meta["concept"] = req.concept
    doc_id = kb.ingest_text(
        req.text,
        source="webui",
        source_type="manual",
        title=req.title or (f"{req.domain}/{req.concept}" if req.domain else "manual"),
        meta=meta if meta else None,
    )
    return {"status": "ok", "doc_id": doc_id}


@app.delete("/api/kb/documents/{doc_id}")
def kb_delete_document(doc_id: str):
    kb = _get_kb()
    kb.delete(doc_id)
    return {"status": "ok"}


@app.post("/api/kb/repair")
def kb_repair():
    kb = _get_kb()
    count = kb.repair()
    return {"status": "ok", "repaired": count}


# ── TTS / STT ─────────────────────────────────────────────────────────────────

class TTSSynthesizeRequest(BaseModel):
    text: str


class TTSConfigSaveRequest(BaseModel):
    provider: str = "edge"
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    output_format: str = "mp3"
    openai_model: str = "tts-1"
    openai_base_url: str = ""
    openai_api_key: str = ""
    kokoro_model_path: str = ""
    kokoro_device: str = "auto"
    kokoro_hf_repo_id: str = "hexgrad/Kokoro-82M"
    hf_endpoint: str = ""
    hf_token: str = ""


class STTConfigSaveRequest(BaseModel):
    provider: str = "openai"
    language: str = "zh"
    openai_model: str = "whisper-1"
    openai_base_url: str = ""
    openai_api_key: str = ""
    local_model_size: str = "base"
    local_model_path: str = ""
    local_device: str = "auto"
    local_compute_type: str = "int8"
    local_hf_repo_id: str = ""
    hf_endpoint: str = ""
    hf_token: str = ""


def _get_tts():
    global _tts_engine
    if _tts_engine is None:
        from tts import TTSEngine
        from config.tts.tts_config import TTSConfig
        cfg = (
            TTSConfig.from_yaml(str(paths.tts_config_yaml))
            if paths.tts_config_yaml.exists()
            else TTSConfig()
        )
        _tts_engine = TTSEngine.from_config(cfg)
    return _tts_engine


def _get_stt():
    global _stt_engine
    if _stt_engine is None:
        from tts import STTEngine
        from config.tts.stt_config import STTConfig
        cfg = (
            STTConfig.from_yaml(str(paths.stt_config_yaml))
            if paths.stt_config_yaml.exists()
            else STTConfig()
        )
        _stt_engine = STTEngine.from_config(cfg)
    return _stt_engine


@app.get("/api/tts/config")
def get_tts_config():
    from config.tts.tts_config import TTSConfig
    cfg = (
        TTSConfig.from_yaml(str(paths.tts_config_yaml))
        if paths.tts_config_yaml.exists()
        else TTSConfig()
    )
    return {
        "provider":          cfg.provider,
        "voice":             cfg.voice,
        "rate":              cfg.rate,
        "volume":            cfg.volume,
        "output_format":     cfg.output_format,
        "openai_model":      cfg.openai_model,
        "openai_base_url":   cfg.openai_base_url,
        "openai_api_key":    cfg.openai_api_key,
        "kokoro_model_path": cfg.kokoro_model_path,
        "kokoro_device":     cfg.kokoro_device,
        "kokoro_hf_repo_id": cfg.kokoro_hf_repo_id,
        "hf_endpoint":       cfg.hf_endpoint,
        "hf_token":          cfg.hf_token,
    }


@app.post("/api/tts/config/save")
def save_tts_config(req: TTSConfigSaveRequest):
    import yaml
    os.makedirs(paths.tts_config_yaml.parent, exist_ok=True)
    data = {
        "provider":          req.provider,
        "voice":             req.voice,
        "rate":              req.rate,
        "volume":            req.volume,
        "output_format":     req.output_format,
        "openai_model":      req.openai_model,
        "openai_base_url":   req.openai_base_url,
        "openai_api_key":    req.openai_api_key,
        "kokoro_model_path": req.kokoro_model_path,
        "kokoro_device":     req.kokoro_device,
        "kokoro_hf_repo_id": req.kokoro_hf_repo_id,
        "hf_endpoint":       req.hf_endpoint,
        "hf_token":          req.hf_token,
    }
    with open(paths.tts_config_yaml, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    global _tts_engine
    _tts_engine = None
    return {"status": "ok"}


@app.get("/api/stt/config")
def get_stt_config():
    from config.tts.stt_config import STTConfig
    cfg = (
        STTConfig.from_yaml(str(paths.stt_config_yaml))
        if paths.stt_config_yaml.exists()
        else STTConfig()
    )
    return {
        "provider":           cfg.provider,
        "language":           cfg.language,
        "openai_model":       cfg.openai_model,
        "openai_base_url":    cfg.openai_base_url,
        "openai_api_key":     cfg.openai_api_key,
        "local_model_size":   cfg.local_model_size,
        "local_model_path":   cfg.local_model_path,
        "local_device":       cfg.local_device,
        "local_compute_type": cfg.local_compute_type,
        "local_hf_repo_id":   cfg.local_hf_repo_id,
        "hf_endpoint":        cfg.hf_endpoint,
        "hf_token":           cfg.hf_token,
    }


@app.post("/api/stt/config/save")
def save_stt_config(req: STTConfigSaveRequest):
    import yaml
    os.makedirs(paths.stt_config_yaml.parent, exist_ok=True)
    data = {
        "provider":           req.provider,
        "language":           req.language,
        "openai_model":       req.openai_model,
        "openai_base_url":    req.openai_base_url,
        "openai_api_key":     req.openai_api_key,
        "local_model_size":   req.local_model_size,
        "local_model_path":   req.local_model_path,
        "local_device":       req.local_device,
        "local_compute_type": req.local_compute_type,
        "local_hf_repo_id":   req.local_hf_repo_id,
        "hf_endpoint":        req.hf_endpoint,
        "hf_token":           req.hf_token,
    }
    with open(paths.stt_config_yaml, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    global _stt_engine
    _stt_engine = None
    return {"status": "ok"}


@app.post("/api/tts/synthesize")
async def tts_synthesize(req: TTSSynthesizeRequest):
    engine = _get_tts()
    audio = await engine.synthesize(req.text)
    return Response(content=audio, media_type="audio/mpeg")


@app.websocket("/ws/tts")
async def ws_tts(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_json()
    text = data.get("text", "")
    if not text:
        await websocket.send_json({"error": "No text provided."})
        await websocket.close()
        return
    engine = _get_tts()
    async for chunk in engine.stream(text):
        await websocket.send_bytes(chunk)
    await websocket.close()


@app.post("/api/stt/transcribe")
async def stt_transcribe(audio: UploadFile = File(...)):
    engine = _get_stt()
    data = await audio.read()
    mime = audio.content_type or "audio/webm"
    text = await engine.transcribe(data, mime)
    return {"text": text}


@app.get("/api/tts/download")
def tts_download():
    """Stream Kokoro model download progress as SSE."""
    from config.tts.tts_config import TTSConfig
    cfg = (
        TTSConfig.from_yaml(str(paths.tts_config_yaml))
        if paths.tts_config_yaml.exists()
        else TTSConfig()
    )
    repo_id  = cfg.kokoro_hf_repo_id or "hexgrad/Kokoro-82M"
    safe     = repo_id.replace("/", "--")
    local_dir = os.path.join("models", "kokoro", safe)

    def generate():
        import queue, threading
        q: queue.Queue = queue.Queue()

        def _dl():
            from huggingface_hub import snapshot_download
            kw: dict = {"local_dir": local_dir}
            if cfg.hf_endpoint:
                kw["endpoint"] = cfg.hf_endpoint
            if cfg.hf_token:
                kw["token"] = cfg.hf_token
            q.put(json.dumps({"status": "start", "repo": repo_id, "local_dir": local_dir}))
            path = snapshot_download(repo_id=repo_id, **kw)
            q.put(json.dumps({"status": "done", "path": path}))

        threading.Thread(target=_dl, daemon=True).start()
        while True:
            msg = q.get()
            yield f"data: {msg}\n\n"
            if json.loads(msg).get("status") in ("done", "error"):
                break

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/stt/download")
def stt_download():
    """Stream faster-whisper model download progress as SSE."""
    from config.tts.stt_config import STTConfig
    cfg = (
        STTConfig.from_yaml(str(paths.stt_config_yaml))
        if paths.stt_config_yaml.exists()
        else STTConfig()
    )
    repo_id  = cfg.local_hf_repo_id or f"Systran/faster-whisper-{cfg.local_model_size}"
    safe     = repo_id.replace("/", "--")
    local_dir = os.path.join("models", "whisper", safe)

    def generate():
        import queue, threading
        q: queue.Queue = queue.Queue()

        def _dl():
            from huggingface_hub import snapshot_download
            kw: dict = {"local_dir": local_dir}
            if cfg.hf_endpoint:
                kw["endpoint"] = cfg.hf_endpoint
            if cfg.hf_token:
                kw["token"] = cfg.hf_token
            q.put(json.dumps({"status": "start", "repo": repo_id, "local_dir": local_dir}))
            path = snapshot_download(repo_id=repo_id, **kw)
            q.put(json.dumps({"status": "done", "path": path}))

        threading.Thread(target=_dl, daemon=True).start()
        while True:
            msg = q.get()
            yield f"data: {msg}\n\n"
            if json.loads(msg).get("status") in ("done", "error"):
                break

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.websocket("/ws/stt")
async def ws_stt(websocket: WebSocket):
    await websocket.accept()
    chunks: list[bytes] = []
    mime_type = "audio/webm"
    while True:
        msg = await websocket.receive()
        if "bytes" in msg:
            chunks.append(msg["bytes"])
        elif "text" in msg:
            import json as _json
            payload = _json.loads(msg["text"])
            if payload.get("done"):
                mime_type = payload.get("mime_type", mime_type)
                break
    audio = b"".join(chunks)
    engine = _get_stt()
    text = await engine.transcribe(audio, mime_type)
    await websocket.send_json({"text": text})
    await websocket.close()


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()
