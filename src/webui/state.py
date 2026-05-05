from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    # ── LLM ───────────────────────────────────────────────────────────────────
    llm: Any = None                   # LLM | None
    llm_cfg: Any = None               # LLMConfig | None
    prompt_lang: str = "cn"

    # ── ReAct ─────────────────────────────────────────────────────────────────
    conv_loop: Any = None             # ConvLoop | None
    active_tao: Any = None            # TaoLoop | None
    react_init_error: str = ""

    # ── Streaming lifecycle (thread-safe) ────────────────────────────────────
    current_gen_id: str | None = None
    react_init_event: threading.Event = field(default_factory=threading.Event)

    # ── Async event loop ──────────────────────────────────────────────────────
    main_event_loop: Any = None       # asyncio.AbstractEventLoop | None
    scheduler_future: Any = None
    preload_future: Any = None

    # ── Infrastructure (set in startup) ──────────────────────────────────────
    task_runner: Any = None
    vllm_manager: Any = None
    searxng_manager: Any = None
    sandbox_manager: Any = None
    service_registry: Any = None
    tool_manager: Any = None

    # ── Plan orchestration ────────────────────────────────────────────────────
    active_orchestrator: Any = None   # PlanOrchestrator | None
    plan_event_queue: Any = None      # asyncio.Queue[PlanEvent] | None

    # ── Knowledge base ────────────────────────────────────────────────────────
    kb: Any = None
    kb_cfg: Any = None

    # ── TTS / STT (lazy) ──────────────────────────────────────────────────────
    tts_engine: Any = None
    stt_engine: Any = None

    # ── Path constants (populated in __post_init__) ───────────────────────────
    llm_config_yaml: str = ""
    vllm_config_yaml: str = ""
    memory_config_yaml: str = ""
    sandbox_config_yaml: str = ""
    webui_settings_json: str = ""
    cache: Any = None                 # StorageConfig
    history_dir: str = ""
    persona_dir: str = ""
    persona_cfg_file: str = ""

    # Private: protect _is_streaming / current_gen_id with a lock
    def __post_init__(self) -> None:
        self._streaming_lock: threading.Lock = threading.Lock()
        self._is_streaming: bool = False
        self.react_init_event.set()   # initially "ready / idle"
        self._init_paths()
        self._init_infra()

    # ── Thread-safe streaming state ───────────────────────────────────────────

    @property
    def is_streaming(self) -> bool:
        with self._streaming_lock:
            return self._is_streaming

    def set_streaming(self, val: bool, gen_id: str | None = None) -> None:
        with self._streaming_lock:
            self._is_streaming = val
            self.current_gen_id = gen_id if val else None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _init_paths(self) -> None:
        from config import paths
        from config.storage import StorageConfig

        self.llm_config_yaml     = str(paths.llm_config_yaml)
        self.vllm_config_yaml    = str(paths.vllm_config_yaml)
        self.memory_config_yaml  = str(paths.memory_config_yaml)
        self.sandbox_config_yaml = str(paths.sandbox_config_yaml)
        self.webui_settings_json = str(paths.webui_settings_json)
        self.cache               = StorageConfig(root=str(paths.cache_root))
        self.history_dir         = self.cache.history_dir
        self.persona_dir         = self.cache.persona_dir
        self.persona_cfg_file    = os.path.join(self.persona_dir, "persona_config.json")

    def _init_infra(self) -> None:
        from infra.task_runner import BackgroundTaskRunner
        from infra.vllm_server import VLLMServerManager
        from infra.searxng_manager import SearXNGManager
        from infra.sandbox import SandboxManager
        from infra.service_registry import ServiceRegistry
        from agent.react.action.manager import ToolManager
        from config.knowledge.config import KnowledgeConfig
        from config.agent.run_config import RunConfig
        from config.infra.sandbox_config import SandboxConfig
        from config import paths

        self.task_runner      = BackgroundTaskRunner(max_workers=8)
        self.vllm_manager     = VLLMServerManager()

        run_cfg = RunConfig.load()
        self.searxng_manager = SearXNGManager(
            container_name = run_cfg.searxng.container_name,
            image          = run_cfg.searxng.image,
            host_port      = run_cfg.searxng.host_port,
            container_port = run_cfg.searxng.container_port,
            settings_yml   = str(paths.searxng_settings_yml),
        )

        self.sandbox_manager  = SandboxManager()
        self.service_registry = ServiceRegistry()
        self.service_registry.register("vllm",    self.vllm_manager)
        self.service_registry.register("searxng", self.searxng_manager)
        self.service_registry.register("sandbox", self.sandbox_manager)

        # Sandbox config
        if os.path.exists(self.sandbox_config_yaml):
            self.sandbox_manager._cfg = SandboxConfig.from_yaml(self.sandbox_config_yaml)
        else:
            self.sandbox_manager._cfg = SandboxConfig(
                workspace_root=self.cache.workspace_dir
            )
        self.sandbox_manager.start()

        self.tool_manager = ToolManager()
        self.kb_cfg       = KnowledgeConfig()


# ── Lazy singleton ────────────────────────────────────────────────────────────
_state: AppState | None = None


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state
