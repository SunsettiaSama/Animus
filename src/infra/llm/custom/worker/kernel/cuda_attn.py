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
    fa2_fwd(q, k, v, causal=True, group_size=1)          -> Tensor
    paged_attn2_fwd(q, k_cache, v_cache,
                    block_table,
                    context_lens,
                    group_size=1,
                    q_start_pos=-1)                       -> Tensor

group_size  = H_q / H_kv.  Pass 1 for MHA.
q_start_pos = absolute position of q[:,.,0,.] in the full sequence.
              -1 disables causal masking (initial prefill, full context).
              >=0 enables per-row causal masking:
                  decode  → q_start_pos = context_len - 1  (Sq=1)
                  verify  → q_start_pos = context_len_before_draft (Sq=k+1)
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
# PyTorch reference fallbacks (always available)
# ─────────────────────────────────────────────────────────────────────────────

def _ref_attn_pytorch(
    q:          torch.Tensor,   # [B, H_q,  Sq, D]
    k:          torch.Tensor,   # [B, H_kv, Sk, D]
    v:          torch.Tensor,   # [B, H_kv, Sk, D]
    causal:     bool = True,
    group_size: int  = 1,
) -> torch.Tensor:
    """Exact scaled-dot-product attention; supports GQA via group_size."""
    if group_size > 1:
        # Expand K/V from H_kv to H_q so standard einsum applies.
        k = k.repeat_interleave(group_size, dim=1)
        v = v.repeat_interleave(group_size, dim=1)

    scale  = 1.0 / math.sqrt(q.shape[-1])
    scores = torch.einsum("bhsd,bhkd->bhsk", q.float(), k.float()) * scale
    if causal:
        Sq, Sk = q.shape[2], k.shape[2]
        mask = torch.ones(Sq, Sk, device=q.device, dtype=torch.bool).tril()
        scores = scores.masked_fill(~mask, float("-inf"))
    attn = torch.softmax(scores, dim=-1)
    return torch.einsum("bhsk,bhkd->bhsd", attn, v.float()).to(q.dtype)


def _paged_attn_pytorch(
    q:            torch.Tensor,   # [B, H_q,  Sq, D]
    k_cache:      torch.Tensor,   # [num_blocks, H_kv, page_size, D]
    v_cache:      torch.Tensor,
    block_table:  torch.Tensor,   # [B, max_pages]  int32
    context_lens: torch.Tensor,   # [B]             int32
    group_size:   int = 1,
    q_start_pos:  int = -1,
) -> torch.Tensor:
    B, H_q, Sq, D = q.shape
    H_kv      = k_cache.shape[1]
    page_size = k_cache.shape[2]
    scale     = 1.0 / math.sqrt(D)
    out       = torch.zeros_like(q)

    for b in range(B):
        ctx   = context_lens[b].item()
        pages = block_table[b].tolist()

        k_seq = torch.zeros(H_kv, ctx, D, dtype=q.dtype, device=q.device)
        v_seq = torch.zeros(H_kv, ctx, D, dtype=q.dtype, device=q.device)
        for pi, phys in enumerate(pages):
            t0     = pi * page_size
            t1     = min(t0 + page_size, ctx)
            actual = t1 - t0
            if actual <= 0:
                break
            k_seq[:, t0:t1, :] = k_cache[phys, :, :actual, :]
            v_seq[:, t0:t1, :] = v_cache[phys, :, :actual, :]

        for h_q in range(H_q):
            h_kv = h_q // group_size
            sc   = torch.einsum("qd,kd->qk",
                                q[b, h_q].float(),
                                k_seq[h_kv].float()) * scale  # [Sq, ctx]

            if q_start_pos >= 0:
                q_pos  = torch.arange(q_start_pos, q_start_pos + Sq, device=q.device)
                kv_pos = torch.arange(ctx, device=q.device)
                causal = kv_pos[None, :] > q_pos[:, None]   # [Sq, ctx]
                sc     = sc.masked_fill(causal, float("-inf"))

            attn        = torch.softmax(sc, dim=-1)
            out[b, h_q] = torch.einsum("qk,kd->qd",
                                       attn, v_seq[h_kv].float()).to(q.dtype)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fa2_fwd(
    q:          torch.Tensor,
    k:          torch.Tensor,
    v:          torch.Tensor,
    causal:     bool = True,
    group_size: int  = 1,
) -> torch.Tensor:
    """Flash Attention 2 forward (contiguous KV, GQA-aware).

    Dispatches to:
      1. CUDA C++ kernel  — if extension loaded and tensors are fp16 on GPU
      2. Triton kernel    — Linux + Triton available
      3. PyTorch fallback — always
    """
    if _try_load_ext() and q.is_cuda and q.dtype == torch.float16:
        return _EXT.fa2_fwd(q, k, v, causal, group_size)

    if sys.platform != "win32":
        try:
            from infra.llm.custom.worker.kernel.flash_attn import flash_attn
            if not causal:
                return flash_attn(q, k, v, group_size=group_size)
        except Exception:
            pass

    return _ref_attn_pytorch(q, k, v, causal, group_size)


def paged_attn2_fwd(
    q:            torch.Tensor,
    k_cache:      torch.Tensor,
    v_cache:      torch.Tensor,
    block_table:  torch.Tensor,
    context_lens: torch.Tensor,
    group_size:   int = 1,
    q_start_pos:  int = -1,
) -> torch.Tensor:
    """Paged Attention 2 forward (paged KV cache, GQA-aware, causal-batch-prefill).

    q_start_pos:
        -1   → no causal mask  (initial prefill, full bidirectional context)
        >=0  → per-row causal  (decode: ctx-1; verify: offset before draft tokens)

    Dispatches to:
      1. CUDA C++ kernel  — if extension loaded and tensors are fp16 on GPU
      2. Triton kernel    — Linux + Triton available
      3. PyTorch fallback — always
    """
    if _try_load_ext() and q.is_cuda and q.dtype == torch.float16:
        return _EXT.paged_attn2_fwd(
            q, k_cache, v_cache, block_table, context_lens, group_size, q_start_pos
        )

    if sys.platform != "win32":
        try:
            from infra.llm.custom.worker.kernel.paged_attn import paged_attn
            scale = 1.0 / math.sqrt(q.shape[-1])
            return paged_attn(
                q, k_cache, v_cache, block_table, context_lens,
                scale, group_size, q_start_pos,
            )
        except Exception:
            pass

    return _paged_attn_pytorch(
        q, k_cache, v_cache, block_table, context_lens, group_size, q_start_pos
    )
