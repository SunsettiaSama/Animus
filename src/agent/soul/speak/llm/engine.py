from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from infra.llm import BaseLLM
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

# 推理模型（如 MiniMax-M3）会在 content 里先吐 <think>…</think> 再给正文；
# speak 域的台词/解析一律不要思考过程，在引擎出口统一剥除。
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """剥除完整 <think> 块；未闭合的前置思考（截断）整段丢弃。"""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    open_idx = cleaned.lower().find(_THINK_OPEN)
    if open_idx != -1:
        cleaned = cleaned[:open_idx]
    return cleaned.strip()


def _stream_no_think(chunks: Iterator[str]) -> Iterator[str]:
    """流式剥 think：先缓冲到能判定是否有思考前缀，思考中不发射。"""
    buf = ""
    decided = False
    for chunk in chunks:
        buf += chunk
        if not decided:
            stripped_head = buf.lstrip()[: len(_THINK_OPEN)]
            if stripped_head.lower() == _THINK_OPEN or _THINK_OPEN.startswith(
                stripped_head.lower()
            ):
                close = buf.lower().find(_THINK_CLOSE)
                if close == -1:
                    continue  # 仍在思考，继续缓冲
                buf = buf[close + len(_THINK_CLOSE):]
                decided = True
            elif len(buf.lstrip()) >= len(_THINK_OPEN):
                decided = True
            else:
                continue  # 前缀太短，还判定不了
        if decided:
            out = strip_think(buf)
            if out:
                yield out
            buf = ""
    if buf:
        out = strip_think(buf)
        if out:
            yield out


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
        text = strip_think(raw) or raw.strip()
        return SpeakLLMResult(text=text, chunks=[text])

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
        yield from _stream_no_think(
            self._require_llm().stream_generate_messages(messages)
        )

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
