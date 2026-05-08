from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from infra.llm.backend import BaseInferenceBackend

if TYPE_CHECKING:
    from config.llm_core.config import LLMConfig
    from config.llm_core.vllm_config import VLLMConfig
    from infra.llm.llm import BaseLLM


class TransformersBackend(BaseInferenceBackend):
    """In-process HuggingFace Transformers inference backend.

    Loads the model directly into the current process via
    ``transformers.AutoModelForCausalLM``.  Works on any platform
    (Windows, Linux, macOS) and serves as the automatic fallback when
    vLLM is requested but the platform is not Linux.

    Model loading is lazy: ``start()`` only records the model name and
    config; the actual ``CausalLLM`` is constructed on the first call
    to ``build_llm()``.  This matches the lifecycle contract expected
    by ``LLMService`` while avoiding an eager GPU memory allocation
    that may not be wanted until the service is actually used.
    """

    _LOG_MAXLEN: int = 200

    def __init__(self) -> None:
        self._state: str = "stopped"
        self._model: str = ""
        self._lock = threading.Lock()
        self._log_lines: list[str] = []

    # ── BaseServiceManager interface ──────────────────────────────────────────

    def start(self, model: str, cfg: VLLMConfig | None = None) -> None:
        with self._lock:
            if self._state in ("starting", "running"):
                return
            self._state = "running"
            self._model = model
            self._log_lines = [
                f"[transformers] backend ready (model={model!r}, lazy load)"
            ]

    def stop(self) -> None:
        with self._lock:
            self._state = "stopped"
            self._model = ""

    def status(self) -> dict:
        with self._lock:
            return {
                "state":    self._state,
                "model":    self._model,
                "provider": self.provider,
            }

    def get_logs(self, n: int = 100) -> list[str]:
        with self._lock:
            return self._log_lines[-n:]

    # ── BaseInferenceBackend interface ────────────────────────────────────────

    def build_llm(self, cfg: LLMConfig) -> BaseLLM:
        from infra.llm.llm import CausalLLM
        return CausalLLM(cfg)

    @property
    def provider(self) -> str:
        return "transformers"
