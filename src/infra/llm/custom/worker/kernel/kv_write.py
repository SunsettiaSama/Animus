from __future__ import annotations

import sys

import torch

_TRITON_AVAILABLE = False
if sys.platform != "win32":
    try:
        import triton
        import triton.language as tl
        _TRITON_AVAILABLE = True
    except ImportError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Triton kernel — KV cache scatter (prefill write)
#
# Scatters a flat [num_tokens, H, D] K (or V) tensor into the pre-allocated
# block pool [num_blocks, H, page_size, D] using the sequence's block_table.
#
# Grid: (num_heads, num_tokens)
# Each program writes one (head, token) slot into its physical block.
# ─────────────────────────────────────────────────────────────────────────────

if _TRITON_AVAILABLE:
    @triton.jit
    def _kv_write_kernel(
        k_in_ptr, v_in_ptr,
        k_pool_ptr, v_pool_ptr,
        block_table_ptr,
        num_tokens,
        stride_kin_t, stride_kin_h, stride_kin_d,
        stride_kp_b,  stride_kp_h,  stride_kp_s,  stride_kp_d,
        stride_btn,
        HEAD_DIM:  tl.constexpr,
        PAGE_SIZE: tl.constexpr,
    ):
        head_id  = tl.program_id(0)
        token_id = tl.program_id(1)

        page_idx   = token_id // PAGE_SIZE
        slot_idx   = token_id  % PAGE_SIZE
        phys_block = tl.load(block_table_ptr + page_idx * stride_btn)

        d_offs = tl.arange(0, HEAD_DIM)

        k_src = k_in_ptr + token_id * stride_kin_t + head_id * stride_kin_h
        k_vec = tl.load(k_src + d_offs * stride_kin_d,
                        mask=token_id < num_tokens, other=0.0)

        v_src = v_in_ptr + token_id * stride_kin_t + head_id * stride_kin_h
        v_vec = tl.load(v_src + d_offs * stride_kin_d,
                        mask=token_id < num_tokens, other=0.0)

        k_dst = (k_pool_ptr + phys_block * stride_kp_b
                 + head_id * stride_kp_h + slot_idx * stride_kp_s)
        v_dst = (v_pool_ptr + phys_block * stride_kp_b
                 + head_id * stride_kp_h + slot_idx * stride_kp_s)

        tl.store(k_dst + d_offs * stride_kp_d, k_vec, mask=token_id < num_tokens)
        tl.store(v_dst + d_offs * stride_kp_d, v_vec, mask=token_id < num_tokens)


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch fallback — identical semantics, used on Windows / no-Triton
# ─────────────────────────────────────────────────────────────────────────────

def kv_write_pytorch(
    k:               torch.Tensor,   # [num_tokens, H, D]
    v:               torch.Tensor,
    k_layer:         torch.Tensor,   # [num_blocks, H, page_size, D]
    v_layer:         torch.Tensor,
    physical_blocks: list[int],
    page_size:       int,
) -> None:
    num_tokens = k.shape[0]
    for token_id in range(num_tokens):
        page_idx = token_id // page_size
        slot_idx = token_id  % page_size
        phys     = physical_blocks[page_idx]
        k_layer[phys, :, slot_idx, :] = k[token_id]
        v_layer[phys, :, slot_idx, :] = v[token_id]


# ─────────────────────────────────────────────────────────────────────────────
# Unified dispatch
# ─────────────────────────────────────────────────────────────────────────────

def kv_write(
    k:               torch.Tensor,
    v:               torch.Tensor,
    k_layer:         torch.Tensor,
    v_layer:         torch.Tensor,
    physical_blocks: list[int],
    page_size:       int,
) -> None:
    """Scatter K/V into the block pool — Triton kernel on Linux, PyTorch elsewhere."""
    if _TRITON_AVAILABLE:
        num_tokens = k.shape[0]
        bt = torch.tensor(physical_blocks, dtype=torch.int32, device=k.device)
        grid = (k.shape[1], num_tokens)    # (num_heads, num_tokens)
        _kv_write_kernel[grid](
            k, v, k_layer, v_layer, bt, num_tokens,
            k.stride(0),       k.stride(1),       k.stride(2),
            k_layer.stride(0), k_layer.stride(1), k_layer.stride(2), k_layer.stride(3),
            bt.stride(0),
            HEAD_DIM=k.shape[2], PAGE_SIZE=page_size,
        )
    else:
        kv_write_pytorch(k, v, k_layer, v_layer, physical_blocks, page_size)
