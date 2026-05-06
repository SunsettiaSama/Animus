from __future__ import annotations

from typing import TYPE_CHECKING

from train.sft._base import _BaseSFTTrainer

if TYPE_CHECKING:
    from config.train.lora_config import LoRAConfig
    from config.train.quant_config import QuantConfig
    from config.train.sft_config import SFTConfig


class QLoRATrainer(_BaseSFTTrainer):
    """QLoRA fine-tuning: 4-bit (or 8-bit) bitsandbytes quantization + LoRA.

    Loads the base model in NF4/8-bit via bnb_loader, applies lm_head bf16
    fix, calls prepare_model_for_kbit_training, then injects a LoRA adapter.
    All training logic is inherited from _BaseSFTTrainer.
    """

    def __init__(
        self,
        sft_cfg: SFTConfig,
        lora_cfg: LoRAConfig,
        quant_cfg: QuantConfig,
    ) -> None:
        super().__init__(sft_cfg, lora_cfg)
        self._quant_cfg = quant_cfg

    def setup(self, model_name: str, **kwargs) -> None:
        from train.quant.bnb_loader import load_quantized_model

        attn_impl = self._resolve_attn_implementation()

        self._model, self._tokenizer = load_quantized_model(
            model_name=model_name,
            cfg=self._quant_cfg,
            attn_implementation=attn_impl,
        )

        self._peft_model = self._apply_lora(self._model)

        bits = "4-bit" if self._quant_cfg.load_in_4bit else "8-bit"
        self._add_log(
            f"QLoRATrainer ready: model={model_name} quant={bits} "
            f"attn={attn_impl} dtype={self._quant_cfg.bnb_4bit_compute_dtype}"
        )
        self._status = "ready"
