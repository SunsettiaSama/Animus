from __future__ import annotations

import importlib.util
import os
import sys
import time
from typing import TYPE_CHECKING

from train.base_trainer import BaseTrainer, TrainResult

if TYPE_CHECKING:
    from config.train.lora_config import LoRAConfig
    from config.train.sft_config import SFTConfig
    from train.data.dataset import TrainDataset


class _BaseSFTTrainer(BaseTrainer):
    def __init__(self, sft_cfg: SFTConfig, lora_cfg: LoRAConfig) -> None:
        super().__init__()
        self._sft_cfg = sft_cfg
        self._lora_cfg = lora_cfg
        self._model = None
        self._tokenizer = None
        self._peft_model = None

    # ── Precision detection ───────────────────────────────────────────────────

    def _check_precision(self) -> tuple[bool, bool]:
        import torch

        if not torch.cuda.is_available():
            return False, False
        if self._sft_cfg.bf16:
            cap = torch.cuda.get_device_capability()
            if cap[0] < 8:
                self._add_log(
                    f"GPU compute capability {cap} < (8,0); bf16 unavailable, switching to fp16"
                )
                return False, True
        return self._sft_cfg.bf16, self._sft_cfg.fp16

    # ── Attention implementation ──────────────────────────────────────────────

    def _resolve_attn_implementation(self) -> str:
        impl = self._sft_cfg.attn_implementation
        if impl != "flash_attention_2":
            return impl
        if importlib.util.find_spec("flash_attn") is None:
            self._add_log(
                "flash_attn package not found; falling back to sdpa. "
                "Install with: pip install flash-attn --no-build-isolation"
            )
            return "sdpa"
        return "flash_attention_2"

    # ── Gradient checkpointing ────────────────────────────────────────────────

    def _apply_gradient_checkpointing(self, model) -> None:
        strategy = self._sft_cfg.checkpoint_strategy
        if strategy == "none":
            return
        if strategy == "full":
            model.gradient_checkpointing_enable()
            return
        layers = []
        if hasattr(model, "model") and hasattr(model.model, "layers"):
            layers = list(model.model.layers)
        if not layers:
            model.gradient_checkpointing_enable()
            return
        half = len(layers) // 2
        for layer in layers[half:]:
            if hasattr(layer, "gradient_checkpointing"):
                layer.gradient_checkpointing = True
        self._add_log(
            f"checkpoint_strategy=half: enabled on {len(layers) - half}/{len(layers)} layers"
        )

    # ── LoRA application ──────────────────────────────────────────────────────

    def _apply_lora(self, model):
        from peft import get_peft_model

        peft_model = get_peft_model(model, self._lora_cfg.to_peft_config())
        peft_model.print_trainable_parameters()
        return peft_model

    # ── Unsloth ───────────────────────────────────────────────────────────────

    def _load_with_unsloth(self, model_name: str, dtype, max_seq_length: int, load_in_4bit: bool):
        if importlib.util.find_spec("unsloth") is None:
            raise RuntimeError(
                "use_unsloth=True but the unsloth package is not installed.\n"
                "Install with: pip install unsloth"
            )
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=model_name,
            max_seq_length=max_seq_length,
            dtype=dtype,
            load_in_4bit=load_in_4bit,
        )
        return model, tokenizer

    # ── Shared train ──────────────────────────────────────────────────────────

    def train(self, dataset: TrainDataset) -> TrainResult:
        from trl import SFTTrainer

        if self._peft_model is None:
            raise RuntimeError("Call setup() before train()")

        bf16, fp16 = self._check_precision()
        training_args = self._sft_cfg.to_training_args(bf16=bf16, fp16=fp16)

        from train.sft.callbacks import LossMonitorCallback
        monitor = LossMonitorCallback(
            loss_history=self._loss_history,
            spike_threshold=self._sft_cfg.loss_spike_threshold,
            no_improve_steps=self._sft_cfg.no_improve_steps,
            abort_event=self._abort_event,
        )

        data_cache_dir = os.path.join(self._sft_cfg.output_dir, "data_cache")

        if self._sft_cfg.packing:
            hf_dataset = dataset.to_hf_dataset()
            fmt_func   = dataset.formatting_func
            collator   = None
        elif dataset._cache_tokenized:
            hf_dataset = dataset.to_hf_dataset(
                tokenizer=self._tokenizer,
                cache_dir=data_cache_dir,
            )
            fmt_func = None
            from train.data.collator import make_sft_collator
            collator = make_sft_collator(self._tokenizer)
        else:
            hf_dataset = dataset.to_hf_dataset()
            fmt_func   = dataset.formatting_func
            collator   = None

        self._status = "running"
        t0 = time.perf_counter()

        trainer = SFTTrainer(
            model=self._peft_model,
            args=training_args,
            train_dataset=hf_dataset,
            tokenizer=self._tokenizer,
            packing=self._sft_cfg.packing,
            max_seq_length=self._sft_cfg.max_seq_length,
            formatting_func=fmt_func,
            data_collator=collator,
            callbacks=[monitor],
        )

        profile_steps = int(os.environ.get("PROFILE_STEPS", "0"))
        if profile_steps > 0:
            import torch
            profile_dir = os.path.join(self._sft_cfg.output_dir, "profiler")
            with torch.profiler.profile(
                activities=[
                    torch.profiler.ProfilerActivity.CPU,
                    torch.profiler.ProfilerActivity.CUDA,
                ],
                schedule=torch.profiler.schedule(
                    wait=1, warmup=1, active=profile_steps
                ),
                on_trace_ready=torch.profiler.tensorboard_trace_handler(profile_dir),
            ):
                trainer.train(
                    resume_from_checkpoint=self._sft_cfg.resume_from_checkpoint
                )
        else:
            trainer.train(
                resume_from_checkpoint=self._sft_cfg.resume_from_checkpoint
            )

        elapsed = time.perf_counter() - t0
        self._current_step = trainer.state.global_step
        self._status = "idle"

        final_loss = self._loss_history[-1] if self._loss_history else 0.0
        return TrainResult(
            adapter_path=self._sft_cfg.output_dir,
            steps=trainer.state.global_step,
            final_loss=final_loss,
            elapsed_secs=elapsed,
            loss_history=list(self._loss_history),
        )

    # ── Save / merge ──────────────────────────────────────────────────────────

    def save(self, output_dir: str) -> None:
        if self._peft_model is None:
            raise RuntimeError("Model not set up. Call setup() first.")
        os.makedirs(output_dir, exist_ok=True)
        self._peft_model.save_pretrained(output_dir)
        self._add_log(f"LoRA adapter saved → {output_dir}")

    def merge_and_save(self, output_dir: str) -> None:
        if self._peft_model is None:
            raise RuntimeError("Model not set up. Call setup() first.")
        os.makedirs(output_dir, exist_ok=True)
        merged = self._peft_model.merge_and_unload()
        merged.save_pretrained(output_dir)
        self._tokenizer.save_pretrained(output_dir)
        self._add_log(f"Merged model + tokenizer saved → {output_dir}")
