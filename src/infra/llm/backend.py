from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from infra.base_service import BaseServiceManager

if TYPE_CHECKING:
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import BaseLLM


class BaseInferenceBackend(BaseServiceManager):
    """Unified interface for all LLM inference backends.

    Three concrete implementations:
    - TransformersBackend  (in-process HuggingFace, Windows-compatible)
    - OfficialVLLMManager  (subprocess vllm serve, Linux only)
    - CustomVLLMManager    (subprocess custom vllm-clone, Linux only)

    LLMService holds one instance of each and selects based on platform
    and the requested backend.  External callers never interact with
    concrete backends directly — they only see LLMHandle.
    """

    @abstractmethod
    def start(self, model: str, cfg) -> None:
        raise NotImplementedError

    @abstractmethod
    def build_llm(self, cfg: LLMConfig) -> BaseLLM:
        raise NotImplementedError

    @property
    @abstractmethod
    def provider(self) -> str:
        raise NotImplementedError
