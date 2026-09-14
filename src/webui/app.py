from __future__ import annotations

import asyncio
import os
import sys
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
# src/webui/ — for routers, state, schemas
sys.path.insert(0, _HERE)
# src/ — for config, react, llm_core, etc.
sys.path.insert(0, os.path.join(_HERE, ".."))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from routers import llm, memory, persona, scheduler, knowledge, voice, history, plan, benchmark, probe, soul, speak, accounts, agent, launch
from routers.infra import router as infra_router
from state import get_state

_HERE = os.path.dirname(__file__)

app = FastAPI(title="ReAct Agent")


@app.middleware("http")
async def _no_cache_js(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/static/js/", "/static/js2/", "/static/hub/")) or request.url.path.startswith("/static/css/"):
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
    agent.router,
    speak.router,
    accounts.router,
    launch.router,
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
        channel_id = (
            str(target.params.get("channel_id", "")).strip()
            or state.default_notify_channel()
        )
        if not channel_id:
            raise RuntimeError("WebUI scheduled delivery requires channel_id")
        session_id = str(target.params.get("session_id", "")).strip()
        if not session_id:
            session_id = f"live:{channel_id}"
        payload = {
            "session_id": session_id,
            "channel_id": channel_id,
            "message": message,
            "source": "scheduler",
            "proactive_intent_id": str(uuid.uuid4()),
            "agent_initiated": True,
            "wait_reply": False,
            "task_name": title,
            "create_window": True,
        }
        soul = getattr(state, "soul_service", None)
        speak = getattr(soul, "_ensure_speak_service", None) if soul is not None else None
        speak_svc = speak() if callable(speak) else None
        if speak_svc is not None and hasattr(speak_svc, "enqueue_agent_outbound"):
            speak_svc.enqueue_agent_outbound(payload)
            return
        from agent.adapters.react_bridge import queue_agent_proactive_session

        queue_agent_proactive_session(state, payload)

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

        # ── 次语言模型（aux）启动注册 ────────────────────────────────────────
        # 必须在 do_soul_init 之前：soul 各子模块经 resolve_module_llm 取 aux，
        # 未注册的槽位会静默回退主模型。
        try:
            from config.llm_core.aux_config import AUX_SLOTS, AuxLLMRegistry
            from config.llm_core.config import LLMConfig

            aux_registry = AuxLLMRegistry.load_default()
            for slot in AUX_SLOTS:
                aux_cfg = aux_registry.slot(slot)
                if not aux_cfg.enabled or aux_cfg.validate():
                    continue
                try:
                    state.llm_service.register_aux(slot, LLMConfig(
                        model=aux_cfg.model,
                        api_key=aux_cfg.api_key,
                        base_url=aux_cfg.base_url or None,
                        max_tokens=aux_cfg.max_tokens,
                        temperature=aux_cfg.temperature,
                        device=aux_cfg.device,
                        backend=aux_cfg.backend,
                    ))
                except Exception as exc:
                    print(f"[webui] aux model {slot!r} register failed: {exc}")
        except Exception as exc:
            print(f"[webui] aux models load failed: {exc}")

        from agent.adapters.soul_bootstrap import do_soul_init

        state.react_init_event.clear()
        state.react_init_error = ""
        state.soul_init_error = ""
        state.conv_loop = None
        do_soul_init(state)

        from worker.state import build_agent_state_service
        from agent.inbound import InboundRouteStore, InboundRouter
        from config.soul.memory.infra_config import SoulMemoryInfraConfig
        from infra.embedding.service import EmbeddingService

        emb_cfg = SoulMemoryInfraConfig.load_default()
        state.inbound_router = InboundRouter(
            store=InboundRouteStore(os.path.join(state.cache.root, "inbound")),
            embedder=EmbeddingService(
                model_name_or_path=emb_cfg.model_name_or_path,
                device=emb_cfg.device,
                use_fp16=emb_cfg.use_fp16,
                batch_size=emb_cfg.batch_size,
                query_prefix=emb_cfg.query_prefix,
                passage_prefix=emb_cfg.passage_prefix,
            ),
            llm=state.llm,
        )

        state.worker_state_service = build_agent_state_service(
            state_dir=state.worker_state_dir,
            llm=state.llm,
            soul=state.soul_service,
            medium_dir=state.cache.memory_dir,
            task_runner=state.task_runner,
        )
        # Portraits are readable immediately; reflection evolves after Worker turns.
        _ = state.worker_state_service.snapshot()
        if state.work_service is not None:
            state.work_service.bind_agent_state_service(state.worker_state_service)
            from config.agent.risk_config import RiskConfig
            from worker.tools.risk.gate import RiskGate

            state.work_service.bind_runtime(
                sandbox=state.sandbox_manager,
                risk_gate=RiskGate.from_config(RiskConfig()),
            )
            if state.soul_service is not None:
                from agent.soul.speak.io.outbound.character import CallableCharacterWorkPort

                work_svc = state.work_service
                soul = state.soul_service

                def _character_work_runner(goal, *, session_id="", user_text=""):
                    return work_svc.run_lightweight_goal(
                        goal,
                        session_id=session_id,
                        user_text=user_text,
                        soul=soul,
                    )

                soul.attach_character_work_port(
                    CallableCharacterWorkPort(_character_work_runner)
                )
        state.worker_state_service.submit_refresh_fallback(force=False)
        print("[webui] Worker AgentStateService loaded")

        # Scheduler is a host service around the already-running Soul/Speak,
        # not the primary WebUI dialogue runtime.
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
            soul_service=state.soul_service,
        )
        _agent_service.start()
        state.scheduler_engine = _agent_service.engine
        state.agent_service = _agent_service
        print("[webui] Scheduler host started after Soul/Speak bootstrap")

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
        state.soul_init_error = str(exc)
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
    if state.agent_service is not None and state.agent_service.is_running:
        state.agent_service.stop()
    elif state.soul_service is not None and getattr(state.soul_service, "is_running", False):
        state.soul_service.stop()
    state.soul_service = None
    if state.scheduler_engine is not None and getattr(state.scheduler_engine, "is_clock_running", False):
        state.scheduler_engine.stop()
    if state.session_manager is not None:
        state.session_manager.stop_all()
        state.session_manager = None
    state.task_runner.shutdown(wait=True, timeout=15)
    state.service_registry.stop_all()
    if state.active_tao is not None:
        state.active_tao.close()
        state.active_tao = None
    from infra.threading import get_thread_registry

    get_thread_registry().stop_all(timeout=5.0)


@app.get("/", response_class=HTMLResponse)
def hub():
    """启动站（进站前）：独立轻页面，不过账号门。见 docs/product/launch-hub-requirements.md §3.2。"""
    html_path = os.path.join(_HERE, "static", "hub", "hub.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


@app.get("/console", response_class=HTMLResponse)
def console():
    """控制室 SPA（进站后）：账号门 → landing/workspace/…，内部逻辑不变。"""
    html_path = os.path.join(_HERE, "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()
