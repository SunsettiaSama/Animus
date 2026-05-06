from __future__ import annotations

import os
from dataclasses import dataclass

_OPTIM_MAP: dict[str, str] = {
    "adamw":        "adamw_torch",
    "adamw_8bit":   "adamw_bnb_8bit",
    "sgd":          "sgd",
    "adafactor":    "adafactor",
    "galore_adamw": "galore_adamw",
}


@dataclass
class SFTConfig:
    output_dir: str = ".react/train/checkpoints"
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 4
    gradient_accumulation_steps: int = 4
    learning_rate: float = 2e-4
    warmup_ratio: float = 0.03
    lr_scheduler_type: str = "cosine"
    max_seq_length: int = 2048

    bf16: bool = True
    fp16: bool = False
    attn_implementation: str = "sdpa"
    use_unsloth: bool = False

    gradient_checkpointing: bool = True
    checkpoint_strategy: str = "full"
    packing: bool = True
    offload_activations: bool = False

    optimizer_type: str = "adamw_8bit"
    max_grad_norm: float = 1.0

    group_by_length: bool = True
    dataloader_num_workers: int = 4
    dataloader_pin_memory: bool = True

    save_steps: int = 100
    logging_steps: int = 10
    resume_from_checkpoint: str | None = None
    report_to: str = "none"

    loss_spike_threshold: float = 10.0
    no_improve_steps: int = 0

    @classmethod
    def from_yaml(cls, path: str) -> SFTConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            output_dir=data.get("output_dir", ".react/train/checkpoints"),
            num_train_epochs=int(data.get("num_train_epochs", 3)),
            per_device_train_batch_size=int(data.get("per_device_train_batch_size", 4)),
            gradient_accumulation_steps=int(data.get("gradient_accumulation_steps", 4)),
            learning_rate=float(data.get("learning_rate", 2e-4)),
            warmup_ratio=float(data.get("warmup_ratio", 0.03)),
            lr_scheduler_type=data.get("lr_scheduler_type", "cosine"),
            max_seq_length=int(data.get("max_seq_length", 2048)),
            bf16=bool(data.get("bf16", True)),
            fp16=bool(data.get("fp16", False)),
            attn_implementation=data.get("attn_implementation", "sdpa"),
            use_unsloth=bool(data.get("use_unsloth", False)),
            gradient_checkpointing=bool(data.get("gradient_checkpointing", True)),
            checkpoint_strategy=data.get("checkpoint_strategy", "full"),
            packing=bool(data.get("packing", True)),
            offload_activations=bool(data.get("offload_activations", False)),
            optimizer_type=data.get("optimizer_type", "adamw_8bit"),
            max_grad_norm=float(data.get("max_grad_norm", 1.0)),
            group_by_length=bool(data.get("group_by_length", True)),
            dataloader_num_workers=int(data.get("dataloader_num_workers", 4)),
            dataloader_pin_memory=bool(data.get("dataloader_pin_memory", True)),
            save_steps=int(data.get("save_steps", 100)),
            logging_steps=int(data.get("logging_steps", 10)),
            resume_from_checkpoint=data.get("resume_from_checkpoint") or None,
            report_to=data.get("report_to", "none"),
            loss_spike_threshold=float(data.get("loss_spike_threshold", 10.0)),
            no_improve_steps=int(data.get("no_improve_steps", 0)),
        )

    def to_dict(self) -> dict:
        return {
            "output_dir":                     self.output_dir,
            "num_train_epochs":               self.num_train_epochs,
            "per_device_train_batch_size":    self.per_device_train_batch_size,
            "gradient_accumulation_steps":    self.gradient_accumulation_steps,
            "learning_rate":                  self.learning_rate,
            "warmup_ratio":                   self.warmup_ratio,
            "lr_scheduler_type":              self.lr_scheduler_type,
            "max_seq_length":                 self.max_seq_length,
            "bf16":                           self.bf16,
            "fp16":                           self.fp16,
            "attn_implementation":            self.attn_implementation,
            "use_unsloth":                    self.use_unsloth,
            "gradient_checkpointing":         self.gradient_checkpointing,
            "checkpoint_strategy":            self.checkpoint_strategy,
            "packing":                        self.packing,
            "offload_activations":            self.offload_activations,
            "optimizer_type":                 self.optimizer_type,
            "max_grad_norm":                  self.max_grad_norm,
            "group_by_length":                self.group_by_length,
            "dataloader_num_workers":         self.dataloader_num_workers,
            "dataloader_pin_memory":          self.dataloader_pin_memory,
            "save_steps":                     self.save_steps,
            "logging_steps":                  self.logging_steps,
            "resume_from_checkpoint":         self.resume_from_checkpoint or "",
            "report_to":                      self.report_to,
            "loss_spike_threshold":           self.loss_spike_threshold,
            "no_improve_steps":               self.no_improve_steps,
        }

    def save_yaml(self, path: str) -> None:
        import yaml

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False)

    def to_training_args(self, bf16: bool | None = None, fp16: bool | None = None):
        from transformers import TrainingArguments

        _bf16 = bf16 if bf16 is not None else self.bf16
        _fp16 = fp16 if fp16 is not None else self.fp16
        optim = _OPTIM_MAP.get(self.optimizer_type, "adamw_bnb_8bit")

        if self.optimizer_type == "galore_adamw":
            import importlib.util
            if importlib.util.find_spec("galore_torch") is None:
                raise RuntimeError(
                    "optimizer_type='galore_adamw' requires the galore-torch package.\n"
                    "Install with: pip install galore-torch"
                )

        return TrainingArguments(
            output_dir=self.output_dir,
            num_train_epochs=self.num_train_epochs,
            per_device_train_batch_size=self.per_device_train_batch_size,
            gradient_accumulation_steps=self.gradient_accumulation_steps,
            learning_rate=self.learning_rate,
            warmup_ratio=self.warmup_ratio,
            lr_scheduler_type=self.lr_scheduler_type,
            bf16=_bf16,
            fp16=_fp16,
            gradient_checkpointing=False,
            group_by_length=self.group_by_length,
            dataloader_num_workers=self.dataloader_num_workers,
            dataloader_pin_memory=self.dataloader_pin_memory,
            max_grad_norm=self.max_grad_norm,
            save_steps=self.save_steps,
            logging_steps=self.logging_steps,
            report_to=self.report_to if self.report_to != "none" else "none",
            optim=optim,
        )
