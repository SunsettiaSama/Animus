from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from infra.llm import BaseLLM
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


@dataclass
class SpeakLLMResult:
    """Speak LLM 生成结果。"""

    text: str
    chunks: list[str] = field(default_factory=list)


class SpeakLLMEngine:
    """Speak 域 LLM：text-in / text-out，不依赖 TaoLoop。"""

    def __init__(self, llm: BaseLLM | None = None) -> None:
        self._llm = llm

    @property
    def llm(self) -> BaseLLM | None:
        return self._llm

    def set_llm(self, llm: BaseLLM | None) -> None:
        self._llm = llm

    def _require_llm(self) -> BaseLLM:
        if self._llm is None:
            raise RuntimeError("speak LLM 未配置")
        return self._llm

    @staticmethod
    def build_messages(
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        system_text = system.strip()
        if system_text:
            messages.append(SystemMessage(content=system_text))
        context_text = context.strip()
        if context_text:
            messages.append(SystemMessage(content=context_text))
        messages.append(HumanMessage(content=user_text.strip()))
        return messages

    def generate_messages(self, messages: list[BaseMessage]) -> SpeakLLMResult:
        raw = self._require_llm().generate_messages(messages).strip()
        return SpeakLLMResult(text=raw, chunks=[raw])

    def generate(
        self,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> SpeakLLMResult:
        text = user_text.strip()
        if not text:
            raise ValueError("user_text 不能为空")
        return self.generate_messages(
            self.build_messages(text, system=system, context=context),
        )

    def stream_messages(self, messages: list[BaseMessage]) -> Iterator[str]:
        yield from self._require_llm().stream_generate_messages(messages)

    def stream(
        self,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> Iterator[str]:
        text = user_text.strip()
        if not text:
            raise ValueError("user_text 不能为空")
        yield from self.stream_messages(
            self.build_messages(text, system=system, context=context),
        )

    def generate_stream(
        self,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> SpeakLLMResult:
        chunks = [piece for piece in self.stream(user_text, system=system, context=context) if piece]
        return SpeakLLMResult(text="".join(chunks), chunks=chunks)
