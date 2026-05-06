from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

from train.sft._base import _BaseSFTTrainer

if TYPE_CHECKING:
    from config.train.lora_config import LoRAConfig
    from config.train.sft_config import SFTConfig


class LoRATrainer(_BaseSFTTrainer):
    """Full-precision LoRA fine-tuning without quantization.

    Loads the base model in bf16 or fp16, applies a PEFT LoRA adapter,
    and trains with trl.SFTTrainer.  Optionally delegates model loading
    to Unsloth for additional kernel-level acceleration.
    """

    def __init__(self, sft_cfg: SFTConfig, lora_cfg: LoRAConfig) -> None:
        super().__init__(sft_cfg, lora_cfg)

    def setup(self, model_name: str, **kwargs) -> None:
        import torch

        attn_impl = self._resolve_attn_implementation()
        bf16, _fp16 = self._check_precision()
        dtype = torch.bfloat16 if bf16 else torch.float16

        if self._sft_cfg.use_unsloth:
            self._model, self._tokenizer = self._load_with_unsloth(
                model_name=model_name,
                dtype=dtype,
                max_seq_length=self._sft_cfg.max_seq_length,
                load_in_4bit=False,
            )
            from unsloth import FastLanguageModel
            self._peft_model = FastLanguageModel.get_peft_model(
                self._model,
                r=self._lora_cfg.r,
                lora_alpha=self._lora_cfg.lora_alpha,
                lora_dropout=self._lora_cfg.lora_dropout,
                target_modules=self._lora_cfg.target_modules,
                bias=self._lora_cfg.bias,
            )
        else:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self._model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=dtype,
                device_map="auto",
                attn_implementation=attn_impl,
            )

            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            if self._tokenizer.pad_token is None:
                self._tokenizer.pad_token = self._tokenizer.eos_token
            self._tokenizer.padding_side = "right"

            self._apply_gradient_checkpointing(self._model)
            self._peft_model = self._apply_lora(self._model)

        self._add_log(
            f"LoRATrainer ready: model={model_name} dtype={'bf16' if bf16 else 'fp16'} "
            f"attn={attn_impl} unsloth={self._sft_cfg.use_unsloth}"
        )
        self._status = "ready"
