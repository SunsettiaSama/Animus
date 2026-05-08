from __future__ import annotations

from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PreallocConfig:
    model_name:             str   = "Qwen/Qwen2.5-0.5B-Instruct"
    max_seq_len:            int   = 2048
    page_size:              int   = 16
    gpu_memory_utilization: float = 0.90
    dtype:                  str   = "float16"
    device:                 str   = "cuda:0"


# ─────────────────────────────────────────────────────────────────────────────
# Profile result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProfileResult:
    total_gpu_bytes:       int
    model_weight_bytes:    int
    peak_activation_bytes: int
    num_heads:             int
    head_dim:              int
    num_layers:            int

    @property
    def reserved_bytes(self) -> int:
        return self.model_weight_bytes + self.peak_activation_bytes


# ─────────────────────────────────────────────────────────────────────────────
# GPU profile run
# ─────────────────────────────────────────────────────────────────────────────

def profile_run(cfg: PreallocConfig) -> ProfileResult:
    """Load model, run one max-length forward pass, measure GPU footprint."""
    import torch
    from transformers import AutoModelForCausalLM, AutoConfig

    device     = torch.device(cfg.device)
    torch_dtype = torch.float16 if cfg.dtype == "float16" else torch.bfloat16

    print(f"[profile] loading {cfg.model_name!r} ...")
    model = AutoModelForCausalLM.from_pretrained(
        cfg.model_name, torch_dtype=torch_dtype, device_map=cfg.device,
    )
    model.eval()

    hf_cfg     = AutoConfig.from_pretrained(cfg.model_name)
    num_heads  = getattr(hf_cfg, "num_key_value_heads",
                         getattr(hf_cfg, "num_attention_heads", None))
    head_dim   = getattr(hf_cfg, "head_dim",
                         hf_cfg.hidden_size // hf_cfg.num_attention_heads)
    num_layers = hf_cfg.num_hidden_layers

    total_bytes  = torch.cuda.get_device_properties(device).total_memory
    weight_bytes = sum(p.nbytes for p in model.parameters())

    torch.cuda.reset_peak_memory_stats(device)
    torch.cuda.synchronize(device)
    mem_before = torch.cuda.memory_allocated(device)

    print(f"[profile] dummy forward  seq_len={cfg.max_seq_len} ...")
    dummy = torch.zeros(1, cfg.max_seq_len, dtype=torch.long, device=device)
    with torch.no_grad():
        model(dummy, use_cache=False)

    torch.cuda.synchronize(device)
    peak_bytes       = torch.cuda.max_memory_allocated(device)
    activation_bytes = peak_bytes - mem_before

    del model, dummy
    torch.cuda.empty_cache()

    result = ProfileResult(
        total_gpu_bytes       = total_bytes,
        model_weight_bytes    = weight_bytes,
        peak_activation_bytes = activation_bytes,
        num_heads             = num_heads,
        head_dim              = head_dim,
        num_layers            = num_layers,
    )
    _print_profile(result, cfg)
    return result


def _synthetic_profile(cfg: PreallocConfig) -> ProfileResult:
    """Return plausible numbers without needing a real GPU."""
    total       = 24 * 1024 ** 3
    weights     =  1 * 1024 ** 3
    activations = 256 * 1024 ** 2
    return ProfileResult(
        total_gpu_bytes       = total,
        model_weight_bytes    = weights,
        peak_activation_bytes = activations,
        num_heads             = 8,
        head_dim              = 64,
        num_layers            = 24,
    )


def _print_profile(r: ProfileResult, cfg: PreallocConfig) -> None:
    gb = 1024 ** 3
    print(
        f"\n[profile] GPU total          : {r.total_gpu_bytes/gb:.2f} GB"
        f"\n[profile] model weights      : {r.model_weight_bytes/gb:.2f} GB"
        f"\n[profile] peak activations   : {r.peak_activation_bytes/gb:.2f} GB"
        f"\n[profile] reserved (w+a)     : {r.reserved_bytes/gb:.2f} GB"
        f"\n[profile] free for KV cache  : "
        f"{(r.total_gpu_bytes - r.reserved_bytes)*cfg.gpu_memory_utilization/gb:.2f} GB"
        f"\n[profile] model arch         : "
        f"{r.num_layers} layers, {r.num_heads} KV heads, head_dim={r.head_dim}\n"
    )
