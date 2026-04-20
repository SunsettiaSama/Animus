from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config.llm_core.config import LLMConfig


class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        raise NotImplementedError

    @abstractmethod
    def generate_messages(self, messages: list[BaseMessage]) -> str:
        raise NotImplementedError

    @abstractmethod
    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        raise NotImplementedError


class CausalLLM(BaseLLM):
    def __init__(self, cfg: LLMConfig):
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

        from langchain_community.llms import HuggingFacePipeline

        import torch

        tokenizer = AutoTokenizer.from_pretrained(cfg.model)
        model = AutoModelForCausalLM.from_pretrained(
            cfg.model,
            device_map=cfg.device,
            torch_dtype=torch.float16,
        )
        model.eval()

        pipe = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            do_sample=cfg.do_sample,
            return_full_text=False,
        )
        self._lc_llm = HuggingFacePipeline(pipeline=pipe)
        self._system_prefix = (cfg.system_prompt + "\n\n") if cfg.system_prompt else ""

    def _messages_to_str(self, messages: list[BaseMessage]) -> str:
        parts: list[str] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                parts.append(msg.content)
            elif isinstance(msg, HumanMessage):
                parts.append(f"User: {msg.content}")
            elif isinstance(msg, AIMessage):
                parts.append(f"Assistant: {msg.content}")
        return "\n\n".join(parts)

    def generate(self, prompt: str) -> str:
        return self._lc_llm.invoke(self._system_prefix + prompt)

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        for chunk in self._lc_llm.stream(self._system_prefix + prompt):
            if chunk:
                yield chunk

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        return self._lc_llm.invoke(self._messages_to_str(messages))

    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        for chunk in self._lc_llm.stream(self._messages_to_str(messages)):
            if chunk:
                yield chunk


class OpenAILLM(BaseLLM):
    def __init__(self, cfg: LLMConfig):
        from langchain_openai import ChatOpenAI

        self._lc_llm = ChatOpenAI(
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
        )
        self._system_message = SystemMessage(content=cfg.system_prompt) if cfg.system_prompt else None

    def _build_messages(self, prompt: str) -> list:
        messages = []
        if self._system_message is not None:
            messages.append(self._system_message)
        messages.append(HumanMessage(content=prompt))
        return messages

    def generate(self, prompt: str) -> str:
        response = self._lc_llm.invoke(self._build_messages(prompt))
        return response.content

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        for chunk in self._lc_llm.stream(self._build_messages(prompt)):
            if chunk.content:
                yield chunk.content

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        response = self._lc_llm.invoke(messages)
        return response.content

    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        for chunk in self._lc_llm.stream(messages):
            if chunk.content:
                yield chunk.content


class LLM(BaseLLM):
    def __init__(self, cfg: LLMConfig):
        if cfg.api_key == "":
            self._backend: BaseLLM = CausalLLM(cfg)
        else:
            self._backend = OpenAILLM(cfg)

    def generate(self, prompt: str) -> str:
        return self._backend.generate(prompt)

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        yield from self._backend.stream_generate(prompt)

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        return self._backend.generate_messages(messages)

    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        yield from self._backend.stream_generate_messages(messages)
