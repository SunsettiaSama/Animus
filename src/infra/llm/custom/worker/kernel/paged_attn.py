from __future__ import annotations

import math
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
# Triton kernel — Paged Attention forward (non-contiguous KV via block_table)
#
# KV cache layout : [num_phys_blocks, H, PAGE_SIZE, HEAD_DIM]
# block_table     : [B, max_pages]   int32
#   block_table[b, i] = physical block id for logical page i of sequence b
# context_lens    : [B]  int32  — actual filled tokens per sequence
#
# Structurally identical to flash_attn._flash_attn_fwd.
# The ONLY difference: K/V are fetched via block_table indirection instead of
# a contiguous stride, enabling arbitrary physical page layout.
#
# Grid: (ceil(Sq / BLOCK_M), H, B)
# ─────────────────────────────────────────────────────────────────────────────

if _TRITON_AVAILABLE:
    @triton.jit
    def _paged_attn_fwd(
        Q,
        K_cache, V_cache,
        block_table,
        context_lens,
        Out,
        stride_qb, stride_qh, stride_qm, stride_qd,
        stride_kb, stride_kh, stride_kp, stride_kd,
        stride_vb, stride_vh, stride_vp, stride_vd,
        stride_ob, stride_oh, stride_om, stride_od,
        stride_btb, stride_btn,
        seqlen_q,
        scale,
        HEAD_DIM:  tl.constexpr,
        BLOCK_M:   tl.constexpr,
        PAGE_SIZE: tl.constexpr,
        MAX_PAGES: tl.constexpr,
    ):
        batch_id  = tl.program_id(2)
        head_id   = tl.program_id(1)
        q_tile    = tl.program_id(0)
        q_start   = q_tile * BLOCK_M
        q_offs    = q_start + tl.arange(0, BLOCK_M)
        d_offs    = tl.arange(0, HEAD_DIM)

        Q_ptr = Q + batch_id * stride_qb + head_id * stride_qh
        q = tl.load(
            Q_ptr + q_offs[:, None] * stride_qm + d_offs[None, :] * stride_qd,
            mask=q_offs[:, None] < seqlen_q, other=0.0,
        ).to(tl.float32)

        ctx_len   = tl.load(context_lens + batch_id)
        m_i       = tl.full([BLOCK_M], float("-inf"), dtype=tl.float32)
        l_i       = tl.zeros([BLOCK_M], dtype=tl.float32)
        acc       = tl.zeros([BLOCK_M, HEAD_DIM], dtype=tl.float32)
        page_offs = tl.arange(0, PAGE_SIZE)

        for page_idx in range(0, MAX_PAGES):
            kv_start   = page_idx * PAGE_SIZE
            valid_page = kv_start < ctx_len

            phys_block = tl.load(
                block_table + batch_id * stride_btb + page_idx * stride_btn,
                mask=valid_page, other=0,
            )
            kv_offs = kv_start + page_offs

            K_page = K_cache + phys_block * stride_kb + head_id * stride_kh
            k = tl.load(
                K_page + d_offs[:, None] * stride_kd + page_offs[None, :] * stride_kp,
                mask=(kv_offs[None, :] < ctx_len) & valid_page, other=0.0,
            ).to(tl.float32)

            V_page = V_cache + phys_block * stride_vb + head_id * stride_vh
            v = tl.load(
                V_page + page_offs[:, None] * stride_vp + d_offs[None, :] * stride_vd,
                mask=(kv_offs[:, None] < ctx_len) & valid_page, other=0.0,
            ).to(tl.float32)

            scores     = tl.dot(q, k) * scale
            scores     = tl.where((kv_offs[None, :] < ctx_len) & valid_page,
                                  scores, float("-inf"))
            m_new      = tl.maximum(m_i, tl.max(scores, axis=1))
            exp_scores = tl.exp(scores - m_new[:, None])
            rescale    = tl.exp(m_i - m_new)
            l_i        = l_i * rescale + tl.sum(exp_scores, axis=1)
            acc        = acc * rescale[:, None] + tl.dot(exp_scores, v)
            m_i        = m_new

        out   = (acc / l_i[:, None]).to(tl.float16)
        O_ptr = Out + batch_id * stride_ob + head_id * stride_oh
        tl.store(
            O_ptr + q_offs[:, None] * stride_om + d_offs[None, :] * stride_od,
            out, mask=q_offs[:, None] < seqlen_q,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch fallback — identical semantics, used on Windows / no-Triton
# ─────────────────────────────────────────────────────────────────────────────

def paged_attn_pytorch(
    q:            torch.Tensor,   # [B, H, Sq, D]
    k_layer:      torch.Tensor,   # [num_blocks, H, page_size, D]
    v_layer:      torch.Tensor,
    block_table:  torch.Tensor,   # [B, max_pages]  int32
    context_lens: torch.Tensor,   # [B]             int32
    scale:        float,
) -> torch.Tensor:
    B, H, Sq, D = q.shape
    page_size    = k_layer.shape[2]
    out          = torch.zeros_like(q)
    for b in range(B):
        ctx   = context_lens[b].item()
        pages = block_table[b].tolist()
        k_seq = torch.zeros(H, ctx, D, dtype=q.dtype, device=q.device)
        v_seq = torch.zeros(H, ctx, D, dtype=q.dtype, device=q.device)
        for page_idx, phys in enumerate(pages):
            t0     = page_idx * page_size
            t1     = min(t0 + page_size, ctx)
            actual = t1 - t0
            if actual <= 0:
                break
            k_seq[:, t0:t1, :] = k_layer[phys, :, :actual, :]
            v_seq[:, t0:t1, :] = v_layer[phys, :, :actual, :]
        scores = torch.einsum("hqd,hkd->hqk", q[b].float(), k_seq.float()) * scale
        attn   = torch.softmax(scores, dim=-1)
        out[b] = torch.einsum("hqk,hkd->hqd", attn, v_seq.float()).to(q.dtype)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Unified dispatch
# ─────────────────────────────────────────────────────────────────────────────

def paged_attn(
    q:            torch.Tensor,
    k_layer:      torch.Tensor,
    v_layer:      torch.Tensor,
    block_table:  torch.Tensor,
    context_lens: torch.Tensor,
    scale:        float,
) -> torch.Tensor:
    """Paged attention — dispatches to Triton kernel on Linux, PyTorch fallback elsewhere."""
    if _TRITON_AVAILABLE:
        B, H, Sq, D = q.shape
        max_pages    = block_table.shape[1]
        BLOCK_M      = min(16, Sq)
        out          = torch.empty_like(q)
        grid         = (triton.cdiv(Sq, BLOCK_M), H, B)
        _paged_attn_fwd[grid](
            q, k_layer, v_layer, block_table, context_lens, out,
            q.stride(0),        q.stride(1),        q.stride(2),        q.stride(3),
            k_layer.stride(0),  k_layer.stride(1),  k_layer.stride(2),  k_layer.stride(3),
            v_layer.stride(0),  v_layer.stride(1),  v_layer.stride(2),  v_layer.stride(3),
            out.stride(0),      out.stride(1),      out.stride(2),      out.stride(3),
            block_table.stride(0), block_table.stride(1),
            Sq, scale,
            HEAD_DIM=D, BLOCK_M=BLOCK_M, PAGE_SIZE=k_layer.shape[2], MAX_PAGES=max_pages,
        )
        return out
    return paged_attn_pytorch(q, k_layer, v_layer, block_table, context_lens, scale)
