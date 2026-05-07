from __future__ import annotations

import time
import threading
from abc import ABC, abstractmethod
from typing import Generator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config.llm_core.config import LLMConfig


def _msg_role(msg: BaseMessage) -> str:
    if isinstance(msg, SystemMessage):
        return "system"
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    return "unknown"


def _snapshot(messages: list[BaseMessage], char_limit: int = 500) -> list[dict]:
    return [
        {"role": _msg_role(m), "content": str(getattr(m, "content", ""))[:char_limit]}
        for m in messages
    ]


def _emit_llm_event(
    *,
    session_id: str,
    ts: float,
    model: str,
    call_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    ttfb_ms: float,
    token_source: str,
    messages_snapshot: list[dict],
) -> None:
    from test.obs.collector import get_collector
    from test.obs.events import LLMCallEvent
    get_collector().emit(LLMCallEvent(
        session_id=session_id,
        ts=ts,
        model=model,
        call_type=call_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        ttfb_ms=ttfb_ms,
        token_source=token_source,
        messages_snapshot=messages_snapshot,
    ))


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
        self._model_name = cfg.model or ""
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
        return self._run_generate_instrumented(text, prompt_str=prompt)

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        text = self._apply_chat_template(messages)
        return self._run_generate_instrumented(text, messages=messages)

    def _run_generate_instrumented(
        self,
        text: str,
        prompt_str: str | None = None,
        messages: list[BaseMessage] | None = None,
    ) -> str:
        import torch
        t0 = time.perf_counter()
        inputs = self._tokenizer(text, return_tensors="pt").to(self._model.device)
        prompt_tokens = int(inputs["input_ids"].shape[-1])
        with torch.no_grad():
            output_ids = self._model.generate(**inputs, **self._generation_kwargs())
        new_ids = output_ids[0][inputs["input_ids"].shape[-1]:]
        completion_tokens = int(len(new_ids))
        output = self._tokenizer.decode(new_ids, skip_special_tokens=True)
        latency_ms = (time.perf_counter() - t0) * 1000

        if messages is not None:
            snap = _snapshot(messages)
        else:
            snap = [{"role": "user", "content": (prompt_str or "")[:500]}]

        from test.obs.collector import get_collector
        _emit_llm_event(
            session_id=get_collector().current_session(),
            ts=t0,
            model=self._model_name,
            call_type="generate",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            ttfb_ms=latency_ms,
            token_source="tokenizer",
            messages_snapshot=snap,
        )
        return output

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
        yield from self._run_stream_instrumented(
            text,
            snap=[{"role": "user", "content": prompt[:500]}],
        )

    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        text = self._apply_chat_template(messages)
        yield from self._run_stream_instrumented(text, snap=_snapshot(messages))

    def _run_stream_instrumented(
        self,
        text: str,
        snap: list[dict],
    ) -> Generator[str, None, None]:
        import torch
        from transformers import TextIteratorStreamer

        inputs = self._tokenizer(text, return_tensors="pt").to(self._model.device)
        prompt_tokens = int(inputs["input_ids"].shape[-1])
        streamer = TextIteratorStreamer(
            self._tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )
        gen_kwargs = {**inputs, **self._generation_kwargs(), "streamer": streamer}
        thread = threading.Thread(target=self._model.generate, kwargs=gen_kwargs, daemon=True)

        t0 = time.perf_counter()
        ttfb_ms = 0.0
        first = True
        chunks: list[str] = []

        thread.start()
        for token in streamer:
            if token:
                if first:
                    ttfb_ms = (time.perf_counter() - t0) * 1000
                    first = False
                chunks.append(token)
                yield token
        thread.join()

        latency_ms = (time.perf_counter() - t0) * 1000
        completion_tokens = len(self._tokenizer("".join(chunks))["input_ids"])

        from test.obs.collector import get_collector
        _emit_llm_event(
            session_id=get_collector().current_session(),
            ts=t0,
            model=self._model_name,
            call_type="stream",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            ttfb_ms=ttfb_ms,
            token_source="tokenizer",
            messages_snapshot=snap,
        )

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

        self._model_name = cfg.model or ""
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

    # ── Non-streaming ─────────────────────────────────────────────────────────

    def generate(self, prompt: str) -> str:
        return self.generate_messages(self._build_messages(prompt))

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        t0 = time.perf_counter()
        response = self._lc_llm.invoke(messages)
        latency_ms = (time.perf_counter() - t0) * 1000

        prompt_tokens = 0
        completion_tokens = 0
        token_source = "api"

        usage = response.response_metadata.get("token_usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        if not prompt_tokens and not completion_tokens:
            um = getattr(response, "usage_metadata", None) or {}
            prompt_tokens = um.get("input_tokens", 0)
            completion_tokens = um.get("output_tokens", 0)

        if not prompt_tokens and not completion_tokens:
            from test.benchmark.tokenizer import count_tokens
            prompt_tokens = sum(count_tokens(getattr(m, "content", str(m))) for m in messages)
            completion_tokens = count_tokens(response.content)
            token_source = "estimated"

        from test.obs.collector import get_collector
        _emit_llm_event(
            session_id=get_collector().current_session(),
            ts=t0,
            model=self._model_name,
            call_type="generate",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            ttfb_ms=latency_ms,
            token_source=token_source,
            messages_snapshot=_snapshot(messages),
        )
        return response.content

    # ── Streaming ─────────────────────────────────────────────────────────────

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        yield from self.stream_generate_messages(self._build_messages(prompt))

    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        t0 = time.perf_counter()
        ttfb_ms = 0.0
        first = True
        chunks: list[str] = []
        usage_meta: dict = {}

        for chunk in self._lc_llm.stream(messages):
            if chunk.content:
                if first:
                    ttfb_ms = (time.perf_counter() - t0) * 1000
                    first = False
                chunks.append(chunk.content)
                yield chunk.content
            if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                usage_meta = chunk.usage_metadata

        latency_ms = (time.perf_counter() - t0) * 1000

        prompt_tokens = usage_meta.get("input_tokens", 0)
        completion_tokens = usage_meta.get("output_tokens", 0)
        token_source = "api" if (prompt_tokens or completion_tokens) else "estimated"

        if token_source == "estimated":
            from test.benchmark.tokenizer import count_tokens
            prompt_tokens = sum(count_tokens(getattr(m, "content", str(m))) for m in messages)
            completion_tokens = count_tokens("".join(chunks))

        from test.obs.collector import get_collector
        _emit_llm_event(
            session_id=get_collector().current_session(),
            ts=t0,
            model=self._model_name,
            call_type="stream",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            ttfb_ms=ttfb_ms,
            token_source=token_source,
            messages_snapshot=_snapshot(messages),
        )


class LLM(BaseLLM):
    """Facade that dispatches to the correct backend based on ``cfg.backend``.

    backend="openai"       → OpenAILLM (remote API, e.g. OpenAI, DeepSeek)
    backend="vllm"         → OpenAILLM (local vLLM server, base_url pre-set by LLMService)
    backend="transformers" → CausalLLM (local HuggingFace model, fallback)
    """

    def __init__(self, cfg: LLMConfig):
        backend = cfg.backend
        if backend == "transformers":
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
