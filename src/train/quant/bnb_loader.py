from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.train.quant_config import QuantConfig


def load_quantized_model(
    model_name: str,
    cfg: QuantConfig,
    attn_implementation: str = "sdpa",
):
    if importlib.util.find_spec("bitsandbytes") is None:
        raise RuntimeError(
            "QLoRA requires the bitsandbytes package.\n"
            "Install with: pip install bitsandbytes"
        )

    import torch
    from peft import prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer

    bnb_config = cfg.to_bnb_config()

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        attn_implementation=attn_implementation,
    )

    if hasattr(model, "lm_head") and model.lm_head is not None:
        model.lm_head = model.lm_head.to(torch.bfloat16)

    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    return model, tokenizer
