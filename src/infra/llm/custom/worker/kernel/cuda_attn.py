"""
Python wrapper for the vllm-clone custom CUDA attention extension.

Load order
----------
1. Try to import the pre-built ``vllm_clone_attn`` shared library (.so / .pyd).
2. If not found, attempt JIT compilation via torch.utils.cpp_extension.load().
3. If compilation fails (no CUDA, no compiler), fall back to:
     • Triton paged_attn  (Linux, GPU present)
     • Pure-PyTorch       (Windows / no Triton)

Public API (same signature on all backends)
-------------------------------------------
    fa2_fwd(q, k, v, causal=True)          -> Tensor
    paged_attn2_fwd(q, k_cache, v_cache,
                    block_table,
                    context_lens)           -> Tensor
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Optional

import torch

# ─────────────────────────────────────────────────────────────────────────────
# Extension loader
# ─────────────────────────────────────────────────────────────────────────────

_EXT: Optional[object]    = None
_EXT_LOADED: bool         = False
_CUSTOM_DIR = Path(__file__).parents[2]   # src/infra/llm/custom/


def _try_load_ext() -> bool:
    """Attempt to load the compiled CUDA extension; return True on success."""
    global _EXT, _EXT_LOADED
    if _EXT_LOADED:
        return _EXT is not None

    _EXT_LOADED = True

    if not torch.cuda.is_available():
        return False

    # ── Option 1: pre-built .so / .pyd already on sys.path ───────────────────
    try:
        import vllm_clone_attn as _m
        _EXT = _m
        return True
    except ImportError:
        pass

    # ── Option 2: JIT compilation via cpp_extension.load ─────────────────────
    try:
        from torch.utils.cpp_extension import load

        csrc = _CUSTOM_DIR / "csrc" / "attention"
        nvcc_flags = [
            "-O3", "--use_fast_math",
            "-gencode", "arch=compute_80,code=sm_80",
            "-gencode", "arch=compute_75,code=sm_75",
            "-std=c++17",
        ]
        cxx_flags = ["/O2", "/std:c++17"] if sys.platform == "win32" \
                    else ["-O3", "-std=c++17"]

        _EXT = load(
            name="vllm_clone_attn",
            sources=[
                str(csrc / "flash_attn2.cu"),
                str(csrc / "pybind.cpp"),
            ],
            extra_include_paths=[str(csrc)],
            extra_cuda_cflags=nvcc_flags,
            extra_cflags=cxx_flags,
            verbose=False,
        )
        return True

    except Exception:
        _EXT = None
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch reference fallback (always available)
# ─────────────────────────────────────────────────────────────────────────────

def _ref_attn_pytorch(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    causal: bool = True,
) -> torch.Tensor:
    """Exact scaled-dot-product attention in float32, output cast back to q.dtype."""
    scale  = 1.0 / math.sqrt(q.shape[-1])
    scores = torch.einsum("bhsd,bhkd->bhsk", q.float(), k.float()) * scale
    if causal:
        Sq, Sk = q.shape[2], k.shape[2]
        mask = torch.ones(Sq, Sk, device=q.device, dtype=torch.bool).tril()
        scores = scores.masked_fill(~mask, float("-inf"))
    attn = torch.softmax(scores, dim=-1)
    return torch.einsum("bhsk,bhkd->bhsd", attn, v.float()).to(q.dtype)


def _paged_attn_pytorch(
    q:            torch.Tensor,
    k_cache:      torch.Tensor,
    v_cache:      torch.Tensor,
    block_table:  torch.Tensor,
    context_lens: torch.Tensor,
) -> torch.Tensor:
    B, H, Sq, D = q.shape
    page_size    = k_cache.shape[2]
    scale        = 1.0 / math.sqrt(D)
    out          = torch.zeros_like(q)

    for b in range(B):
        ctx   = context_lens[b].item()
        pages = block_table[b].tolist()
        k_seq = torch.zeros(H, ctx, D, dtype=q.dtype, device=q.device)
        v_seq = torch.zeros(H, ctx, D, dtype=q.dtype, device=q.device)
        for pi, phys in enumerate(pages):
            t0     = pi * page_size
            t1     = min(t0 + page_size, ctx)
            actual = t1 - t0
            if actual <= 0:
                break
            k_seq[:, t0:t1, :] = k_cache[phys, :, :actual, :]
            v_seq[:, t0:t1, :] = v_cache[phys, :, :actual, :]
        sc   = torch.einsum("hqd,hkd->hqk", q[b].float(), k_seq.float()) * scale
        attn = torch.softmax(sc, dim=-1)
        out[b] = torch.einsum("hqk,hkd->hqd", attn, v_seq.float()).to(q.dtype)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fa2_fwd(
    q:      torch.Tensor,
    k:      torch.Tensor,
    v:      torch.Tensor,
    causal: bool = True,
) -> torch.Tensor:
    """Flash Attention 2 forward.

    Dispatches to:
      1. CUDA C++ kernel  — if extension loaded and tensors are fp16 on GPU
      2. Triton kernel    — Linux + Triton available
      3. PyTorch fallback — always
    """
    if _try_load_ext() and q.is_cuda and q.dtype == torch.float16:
        return _EXT.fa2_fwd(q, k, v, causal)

    # Triton path (Linux only)
    if sys.platform != "win32":
        try:
            from infra.llm.custom.worker.kernel.flash_attn import flash_attn
            if not causal:
                return flash_attn(q, k, v)
        except Exception:
            pass

    return _ref_attn_pytorch(q, k, v, causal)


def paged_attn2_fwd(
    q:            torch.Tensor,
    k_cache:      torch.Tensor,
    v_cache:      torch.Tensor,
    block_table:  torch.Tensor,
    context_lens: torch.Tensor,
) -> torch.Tensor:
    """Paged Attention 2 forward.

    Dispatches to:
      1. CUDA C++ kernel  — if extension loaded and tensors are fp16 on GPU
      2. Triton kernel    — Linux + Triton available
      3. PyTorch fallback — always
    """
    if _try_load_ext() and q.is_cuda and q.dtype == torch.float16:
        return _EXT.paged_attn2_fwd(q, k_cache, v_cache, block_table, context_lens)

    if sys.platform != "win32":
        try:
            from infra.llm.custom.worker.kernel.paged_attn import paged_attn
            scale = 1.0 / math.sqrt(q.shape[-1])
            return paged_attn(q, k_cache, v_cache, block_table, context_lens, scale)
        except Exception:
            pass

    return _paged_attn_pytorch(q, k_cache, v_cache, block_table, context_lens)
