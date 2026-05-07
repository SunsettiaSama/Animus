from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_service: Any = None           # LLMService | None  (set in _init_infra)
    prompt_lang: str = "cn"

    @property
    def llm(self):
        if self.llm_service is None:
            return None
        return self.llm_service.handle

    @property
    def llm_cfg(self):
        if self.llm_service is None:
            return None
        return self.llm_service.cfg

    @property
    def vllm_manager(self):
        if self.service_registry is None:
            return None
        return self.service_registry.get("vllm")

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
    searxng_manager: Any = None
    sandbox_manager: Any = None
    service_registry: Any = None
    tool_manager: Any = None
    bot_service: Any = None           # BotService | None

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

    def try_start_streaming(self, gen_id: str) -> bool:
        """Atomically check-and-set streaming state.

        Returns True (and acquires the streaming slot) only when no other
        stream is active.  The caller must call set_streaming(False) to
        release the slot when the stream ends.
        """
        with self._streaming_lock:
            if self._is_streaming:
                return False
            self._is_streaming = True
            self.current_gen_id = gen_id
            return True

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
        from infra.llm.service import LLMService
        from infra.searxng_manager import SearXNGManager
        from infra.sandbox import SandboxManager
        from infra.service_registry import ServiceRegistry
        from agent.react.action.manager import ToolManager
        from config.knowledge.config import KnowledgeConfig
        from config.agent.run_config import RunConfig
        from config.infra.sandbox_config import SandboxConfig
        from config import paths

        self.task_runner      = BackgroundTaskRunner(max_workers=8)
        _vllm_cfg_path = self.vllm_config_yaml
        import os as _os
        if _os.path.exists(_vllm_cfg_path):
            from config.llm_core.vllm_config import VLLMConfig as _VLLMCfg
            _startup_vllm_cfg = _VLLMCfg.from_yaml(_vllm_cfg_path)
        else:
            from config.llm_core.vllm_config import VLLMConfig as _VLLMCfg
            _startup_vllm_cfg = _VLLMCfg()

        if _startup_vllm_cfg.provider == "custom":
            from infra.llm.custom import CustomVLLMManager
            _vllm_manager = CustomVLLMManager()
        else:
            from infra.llm.official import OfficialVLLMManager
            _vllm_manager = OfficialVLLMManager()

        self.llm_service      = LLMService(_vllm_manager)

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
        self.service_registry.register("llm",     self.llm_service)
        self.service_registry.register("vllm",    _vllm_manager)
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

        # ── Bot service ───────────────────────────────────────────────────────
        from config.infra.bot_config import BotConfig
        from infra.network.bot.service import BotService

        bot_cfg   = BotConfig.load()
        transport = _build_transport(bot_cfg)
        self.bot_service = BotService(transport, self, bot_cfg)
        self.service_registry.register("bot", self.bot_service)


# ── Transport factory ─────────────────────────────────────────────────────────

def _build_transport(bot_cfg: Any) -> Any:
    """根据 bot_config.yaml 中的 transport 字段选择对应的 Transport 实现。

    "forward_ws"  → ForwardWSTransport（对接 NapCat / go-cqhttp 等外部进程）
    "qq_official" → QQOfficialTransport（QQ 官方机器人 API，无需外部进程）
    """
    t = bot_cfg.transport

    if t == "forward_ws":
        from infra.network.bot.onebot.transport.forward_ws import ForwardWSTransport
        return ForwardWSTransport(
            url=bot_cfg.ws_url,
            access_token=bot_cfg.access_token,
            reconnect_interval=bot_cfg.reconnect_interval_sec,
        )

    if t == "qq_official":
        from infra.network.bot.onebot.transport.qq_official import QQOfficialTransport
        return QQOfficialTransport(
            appid=bot_cfg.appid,
            secret=bot_cfg.secret,
            is_sandbox=bot_cfg.is_sandbox,
        )

    raise ValueError(
        f"Unknown bot transport: {t!r}. "
        "Valid options: 'forward_ws', 'qq_official'"
    )


# ── Lazy singleton ────────────────────────────────────────────────────────────
_state: AppState | None = None


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state
