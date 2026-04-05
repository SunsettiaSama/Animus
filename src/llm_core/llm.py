from __future__ import annotations

import copy
from abc import ABC, abstractmethod

from config.llm_core.config import LLMConfig


class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class CausalLLM(BaseLLM):
    def __init__(self, cfg: LLMConfig):
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch

        self.max_new_tokens = cfg.max_tokens
        self.temperature = cfg.temperature
        self.do_sample = cfg.do_sample

        self.tokenizer = AutoTokenizer.from_pretrained(cfg.model)
        self.model = AutoModelForCausalLM.from_pretrained(
            cfg.model,
            device_map=cfg.device,
            torch_dtype=torch.float16,
        )
        self.model.eval()

        self._system_past_kv = None
        self._system_token_len = 0

        if cfg.system_prompt:
            self._precompute_system_kv(cfg.system_prompt)

    def _precompute_system_kv(self, system_prompt: str) -> None:
        import torch

        ids = self.tokenizer(system_prompt, return_tensors="pt")["input_ids"]
        ids = ids.to(self.model.device)
        with torch.no_grad():
            outputs = self.model(ids, use_cache=True)
        self._system_past_kv = outputs.past_key_values
        self._system_token_len = ids.shape[-1]

    def generate(self, prompt: str) -> str:
        import torch

        user_ids = self.tokenizer(prompt, return_tensors="pt")["input_ids"]
        user_ids = user_ids.to(self.model.device)

        if self._system_past_kv is not None:
            full_len = self._system_token_len + user_ids.shape[-1]
            attention_mask = torch.ones(1, full_len, dtype=torch.long, device=self.model.device)
            with torch.no_grad():
                output_ids = self.model.generate(
                    input_ids=user_ids,
                    attention_mask=attention_mask,
                    past_key_values=copy.deepcopy(self._system_past_kv),
                    max_new_tokens=self.max_new_tokens,
                    temperature=self.temperature,
                    do_sample=self.do_sample,
                )
            new_ids = output_ids[0][user_ids.shape[-1]:]
        else:
            attention_mask = torch.ones_like(user_ids)
            with torch.no_grad():
                output_ids = self.model.generate(
                    input_ids=user_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=self.max_new_tokens,
                    temperature=self.temperature,
                    do_sample=self.do_sample,
                )
            new_ids = output_ids[0][user_ids.shape[-1]:]

        return self.tokenizer.decode(new_ids, skip_special_tokens=True)


class OpenAILLM(BaseLLM):
    def __init__(self, cfg: LLMConfig):
        from openai import OpenAI

        self.model = cfg.model
        self.max_tokens = cfg.max_tokens
        self.temperature = cfg.temperature
        self.client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

        self._system_message: dict | None = (
            {"role": "system", "content": cfg.system_prompt} if cfg.system_prompt else None
        )

    def generate(self, prompt: str) -> str:
        messages = []
        if self._system_message is not None:
            messages.append(self._system_message)
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return response.choices[0].message.content


class LLM(BaseLLM):
    def __init__(self, cfg: LLMConfig):
        if cfg.api_key == "":
            self._backend: BaseLLM = CausalLLM(cfg)
        else:
            self._backend = OpenAILLM(cfg)

    def generate(self, prompt: str) -> str:
        return self._backend.generate(prompt)
