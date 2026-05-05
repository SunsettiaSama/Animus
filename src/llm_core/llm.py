from __future__ import annotations

import threading
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
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        self._tokenizer = AutoTokenizer.from_pretrained(cfg.model)
        model = AutoModelForCausalLM.from_pretrained(
            cfg.model,
            device_map=cfg.device,
            torch_dtype=torch.float16,
        )
        model.eval()
        self._model = model
        self._cfg = cfg
        self._system_prompt = cfg.system_prompt

    # ── Prompt building ───────────────────────────────────────────────────────

    def _apply_chat_template(self, messages: list[BaseMessage]) -> str:
        chat: list[dict] = []
        if self._system_prompt:
            chat.append({"role": "system", "content": self._system_prompt})
        for msg in messages:
            if isinstance(msg, SystemMessage):
                chat.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                chat.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                chat.append({"role": "assistant", "content": msg.content})
        return self._tokenizer.apply_chat_template(
            chat,
            tokenize=False,
            add_generation_prompt=True,
        )

    def _prompt_to_messages(self, prompt: str) -> list[dict]:
        chat: list[dict] = []
        if self._system_prompt:
            chat.append({"role": "system", "content": self._system_prompt})
        chat.append({"role": "user", "content": prompt})
        return chat

    def _generation_kwargs(self) -> dict:
        cfg = self._cfg
        kwargs: dict = {
            "max_new_tokens":    cfg.max_tokens,
            "temperature":       cfg.temperature,
            "do_sample":         cfg.do_sample,
            "repetition_penalty": cfg.repetition_penalty,
        }
        if cfg.do_sample:
            if cfg.top_p < 1.0:
                kwargs["top_p"] = cfg.top_p
            if cfg.top_k > 0:
                kwargs["top_k"] = cfg.top_k
        return kwargs

    # ── Non-streaming ─────────────────────────────────────────────────────────

    def generate(self, prompt: str) -> str:
        text = self._tokenizer.apply_chat_template(
            self._prompt_to_messages(prompt),
            tokenize=False,
            add_generation_prompt=True,
        )
        return self._run_generate(text)

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        return self._run_generate(self._apply_chat_template(messages))

    def _run_generate(self, text: str) -> str:
        import torch
        inputs = self._tokenizer(text, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            output_ids = self._model.generate(**inputs, **self._generation_kwargs())
        new_ids = output_ids[0][inputs["input_ids"].shape[-1]:]
        return self._tokenizer.decode(new_ids, skip_special_tokens=True)

    # ── Streaming ─────────────────────────────────────────────────────────────

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        text = self._tokenizer.apply_chat_template(
            self._prompt_to_messages(prompt),
            tokenize=False,
            add_generation_prompt=True,
        )
        yield from self._run_stream(text)

    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        yield from self._run_stream(self._apply_chat_template(messages))

    def _run_stream(self, text: str) -> Generator[str, None, None]:
        import torch
        from transformers import TextIteratorStreamer

        inputs = self._tokenizer(text, return_tensors="pt").to(self._model.device)
        streamer = TextIteratorStreamer(
            self._tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )
        gen_kwargs = {**inputs, **self._generation_kwargs(), "streamer": streamer}

        thread = threading.Thread(target=self._model.generate, kwargs=gen_kwargs, daemon=True)
        thread.start()

        for token in streamer:
            if token:
                yield token

        thread.join()


class OpenAILLM(BaseLLM):
    def __init__(self, cfg: LLMConfig):
        from langchain_openai import ChatOpenAI

        self._lc_llm = ChatOpenAI(
            model=cfg.model,
            api_key=cfg.api_key or "EMPTY",
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
    """Facade that dispatches to the correct backend based on ``cfg.backend``.

    backend="openai"       → OpenAILLM (remote API, e.g. OpenAI, DeepSeek)
    backend="vllm"         → OpenAILLM (local vLLM server, base_url pre-set by caller)
    backend="transformers" → CausalLLM (local HuggingFace model, fallback)
    """

    def __init__(self, cfg: LLMConfig):
        backend = cfg.backend
        if backend == "transformers":
            self._backend: BaseLLM = CausalLLM(cfg)
        else:
            # Both "openai" and "vllm" use the OpenAI-compatible client.
            # For "vllm", the caller (app.py) must have injected cfg.base_url
            # to point at the local vLLM server before constructing this object.
            self._backend = OpenAILLM(cfg)

    def generate(self, prompt: str) -> str:
        return self._backend.generate(prompt)

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        yield from self._backend.stream_generate(prompt)

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        return self._backend.generate_messages(messages)

    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        yield from self._backend.stream_generate_messages(messages)
