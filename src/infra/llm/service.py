from __future__ import annotations

import dataclasses
import sys
from typing import TYPE_CHECKING

from infra.base_service import BaseServiceManager
from infra.llm.backend import BaseInferenceBackend
from infra.llm.base import VLLM_LINUX_ONLY
from infra.llm.handle import LLMHandle

if TYPE_CHECKING:
    from config.llm_core.config import LLMConfig
    from config.llm_core.vllm_config import VLLMConfig


class LLMService(BaseServiceManager):
    """Unified LLM infrastructure coordinator.

    Holds one instance of each of the three inference backends and
    selects the appropriate one based on platform and the requested
    ``cfg.backend`` value:

    +-----------------+------------------+-----------------------------+
    | backend value   | platform         | selected backend            |
    +=================+==================+=============================+
    | "transformers"  | any              | TransformersBackend         |
    | "vllm"          | Linux            | OfficialVLLMManager         |
    | "vllm"          | Windows          | TransformersBackend (degrade)|
    | "vllm-clone"    | Linux            | CustomVLLMManager           |
    | "vllm-clone"    | Windows          | TransformersBackend (degrade)|
    | "openai"        | any              | no subprocess; OpenAILLM    |
    +-----------------+------------------+-----------------------------+

    External callers (TaoLoop, PersonaManager, etc.) receive the single
    canonical ``LLMHandle`` at init time.  Calling ``start()`` or
    ``reload()`` updates the handle in-place — callers never need to do
    anything to pick up backend changes.

    ``status()`` exposes a ``degraded_reason`` key when an automatic
    backend downgrade occurred.
    """

    def __init__(
        self,
        transformers_backend: BaseInferenceBackend,
        vllm_backend: BaseInferenceBackend,
        clone_backend: BaseInferenceBackend,
    ) -> None:
        self._backends: dict[str, BaseInferenceBackend] = {
            "transformers": transformers_backend,
            "vllm":         vllm_backend,
            "vllm-clone":   clone_backend,
        }
        self._handle: LLMHandle | None = None
        self._cfg: LLMConfig | None = None
        self._state: str = "stopped"
        self._degraded_reason: str | None = None

    # ── BaseServiceManager interface ──────────────────────────────────────────

    def start(self, cfg: LLMConfig, vllm_cfg: VLLMConfig | None = None, **kwargs) -> None:
        self._degraded_reason = None

        if cfg.backend in ("vllm", "vllm-clone") and sys.platform == "win32":
            self._degraded_reason = VLLM_LINUX_ONLY
            cfg = dataclasses.replace(cfg, backend="transformers")

        if cfg.backend in self._backends:
            from config.llm_core.vllm_config import VLLMConfig as _VLLMConfig
            backend = self._backends[cfg.backend]
            backend.start(cfg.model, vllm_cfg or _VLLMConfig())
            llm = backend.build_llm(cfg)
        else:
            from infra.llm.llm import LLM
            llm = LLM(cfg)

        if self._handle is None:
            self._handle = LLMHandle(llm)
        else:
            self._handle.update(llm)

        self._cfg = cfg
        self._state = "running"

    def stop(self) -> None:
        if self._cfg and self._cfg.backend in self._backends:
            self._backends[self._cfg.backend].stop()
        self._state = "stopped"

    def status(self) -> dict:
        return {
            "state":          self._state,
            "model":          self._cfg.model   if self._cfg else None,
            "backend":        self._cfg.backend if self._cfg else None,
            "degraded_reason": self._degraded_reason,
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
