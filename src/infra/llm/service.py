from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from infra.base_service import BaseServiceManager
from infra.llm.llm import LLM
from infra.llm.handle import LLMHandle

if TYPE_CHECKING:
    from config.llm_core.config import LLMConfig
    from config.llm_core.vllm_config import VLLMConfig
    from infra.vllm_server import VLLMServerManager


class LLMService(BaseServiceManager):
    """Unified LLM infrastructure service.

    Manages the full lifecycle of an LLM backend:
    - backend="vllm"         : starts/stops the vLLM subprocess, patches cfg.base_url
    - backend="openai"       : creates OpenAILLM directly (no subprocess)
    - backend="transformers" : loads model in-process

    Owns the single canonical LLMHandle.  All consumers (TaoLoop, PersonaManager,
    etc.) receive this handle at init time.  Calling start() or reload() with a
    new LLMConfig calls handle.update(new_llm) internally — callers never need
    to do anything to pick up the change.
    """

    def __init__(self, vllm_manager: VLLMServerManager) -> None:
        self._vllm = vllm_manager
        self._handle: LLMHandle | None = None
        self._cfg: LLMConfig | None = None
        self._state: str = "stopped"

    # ── BaseServiceManager interface ──────────────────────────────────────────

    def start(self, cfg: LLMConfig, vllm_cfg: VLLMConfig | None = None, **kwargs) -> None:
        from config.llm_core.config import LLMConfig as _LLMConfig
        if cfg.backend == "vllm":
            if self._vllm.status().get("state") != "running":
                if vllm_cfg is None:
                    from config.llm_core.vllm_config import VLLMConfig
                    vllm_cfg = VLLMConfig()
                self._vllm.start(cfg.model, vllm_cfg)
            cfg = dataclasses.replace(cfg, base_url=self._vllm.base_url)

        llm = LLM(cfg)
        if self._handle is None:
            self._handle = LLMHandle(llm)
        else:
            self._handle.update(llm)

        self._cfg = cfg
        self._state = "running"

    def stop(self) -> None:
        if self._cfg and self._cfg.backend == "vllm":
            self._vllm.stop()
        self._state = "stopped"

    def status(self) -> dict:
        return {
            "state":   self._state,
            "model":   self._cfg.model   if self._cfg else None,
            "backend": self._cfg.backend if self._cfg else None,
        }

    # ── Public interface for consumers ────────────────────────────────────────

    def reload(self, cfg: LLMConfig, vllm_cfg: VLLMConfig | None = None) -> None:
        self.start(cfg, vllm_cfg=vllm_cfg)

    @property
    def handle(self) -> LLMHandle | None:
        return self._handle

    @property
    def cfg(self) -> LLMConfig | None:
        return self._cfg
