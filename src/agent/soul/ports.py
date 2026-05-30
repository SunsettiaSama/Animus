from __future__ import annotations

from typing import Any, Protocol

from infra.llm import BaseLLM


class LLMServicePort(Protocol):
    """infra LLMService 面向 Soul 的最小接口。"""

    def get_aux_llm(self, name: str) -> BaseLLM | None: ...


class ExternalOpportunitySupplier(Protocol):
    """顶层外界时机探测接口（可为空实现）。"""

    def is_opportune(
        self,
        *,
        session_id: str,
        impulse_level: float,
        expectation: str,
    ) -> bool: ...


class EmbeddingPort(Protocol):
    """顶层 embedding 服务最小接口。"""

    def embed(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class ListEmbeddingAdapter:
    """将仅实现 embed() 的后端适配为 EmbeddingPort。"""

    def __init__(self, backend) -> None:
        self._backend = backend

    def embed(self, text: str) -> list[float]:
        return self._backend.embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._backend.embed(text) for text in texts]


class SpeakDialogueExperiencePort(Protocol):
    """SpeakHandler 访问对话体验栈的窄接口。"""

    def state(self, session_id: str) -> Any | None: ...

    def working_memory_text(self, session_id: str) -> str: ...


class SpeakExperiencePort(Protocol):
    """SpeakHandler 经 L1 注入的体验栈端口（避免 Handler 依赖 SoulService）。"""

    @property
    def dialogue(self) -> SpeakDialogueExperiencePort: ...

    def close_dialogue(self, session_id: str) -> Any | None: ...


class PresenceSnapshotPort(Protocol):
    """Speak compose 读取当下态快照的窄接口（待收敛 C 类横向依赖）。"""

    def snapshot(self, session_id: str = "tao") -> Any: ...
