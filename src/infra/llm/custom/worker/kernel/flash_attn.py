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
# Triton kernel — Flash Attention forward (contiguous KV)
#
# Grid: (ceil(Sq / BLOCK_M), H, B)
# Each program owns one [BLOCK_M, D] output tile and streams over all KV tiles.
# Online softmax (Dao et al. 2022, §3.1) avoids materialising the full score
# matrix, keeping memory usage O(BLOCK_M * D) instead of O(Sq * Sk).
# ─────────────────────────────────────────────────────────────────────────────

if _TRITON_AVAILABLE:
    @triton.jit
    def _flash_attn_fwd(
        Q, K, V, Out,
        stride_qb, stride_qh, stride_qm, stride_qd,
        stride_kb, stride_kh, stride_kn, stride_kd,
        stride_vb, stride_vh, stride_vn, stride_vd,
        stride_ob, stride_oh, stride_om, stride_od,
        seqlen_q, seqlen_k,
        scale,
        HEAD_DIM: tl.constexpr,
        BLOCK_M:  tl.constexpr,
        BLOCK_N:  tl.constexpr,
    ):
        batch_id = tl.program_id(2)
        head_id  = tl.program_id(1)
        q_tile   = tl.program_id(0)

        q_start = q_tile * BLOCK_M
        q_offs  = q_start + tl.arange(0, BLOCK_M)
        d_offs  = tl.arange(0, HEAD_DIM)

        Q_ptr = Q + batch_id * stride_qb + head_id * stride_qh
        q = tl.load(
            Q_ptr + q_offs[:, None] * stride_qm + d_offs[None, :] * stride_qd,
            mask=q_offs[:, None] < seqlen_q, other=0.0,
        ).to(tl.float32)

        m_i = tl.full([BLOCK_M], float("-inf"), dtype=tl.float32)
        l_i = tl.zeros([BLOCK_M], dtype=tl.float32)
        acc = tl.zeros([BLOCK_M, HEAD_DIM], dtype=tl.float32)

        K_ptr = K + batch_id * stride_kb + head_id * stride_kh
        V_ptr = V + batch_id * stride_vb + head_id * stride_vh

        for n_start in range(0, seqlen_k, BLOCK_N):
            n_offs = n_start + tl.arange(0, BLOCK_N)

            k = tl.load(
                K_ptr + d_offs[:, None] * stride_kd + n_offs[None, :] * stride_kn,
                mask=n_offs[None, :] < seqlen_k, other=0.0,
            ).to(tl.float32)

            v = tl.load(
                V_ptr + n_offs[:, None] * stride_vn + d_offs[None, :] * stride_vd,
                mask=n_offs[:, None] < seqlen_k, other=0.0,
            ).to(tl.float32)

            scores     = tl.dot(q, k) * scale
            scores     = tl.where(n_offs[None, :] < seqlen_k, scores, float("-inf"))
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
# Python wrapper
# ─────────────────────────────────────────────────────────────────────────────

def flash_attn(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
    """Flash attention over contiguous [B, H, S, D] tensors.  Linux/Triton only."""
    assert _TRITON_AVAILABLE, "flash_attn requires Triton (Linux)"
    B, H, Sq, D = q.shape
    _, _, Sk, _ = k.shape
    BLOCK_M = 16
    BLOCK_N = 16
    scale   = 1.0 / math.sqrt(D)
    out     = torch.empty_like(q)
    grid    = (triton.cdiv(Sq, BLOCK_M), H, B)
    _flash_attn_fwd[grid](
        q, k, v, out,
        q.stride(0), q.stride(1), q.stride(2), q.stride(3),
        k.stride(0), k.stride(1), k.stride(2), k.stride(3),
        v.stride(0), v.stride(1), v.stride(2), v.stride(3),
        out.stride(0), out.stride(1), out.stride(2), out.stride(3),
        Sq, Sk, scale,
        HEAD_DIM=D, BLOCK_M=BLOCK_M, BLOCK_N=BLOCK_N,
    )
    return out


def ref_attn(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
    """Pure-PyTorch reference attention for correctness comparison."""
    scale  = 1.0 / math.sqrt(q.shape[-1])
    scores = torch.einsum("bhmd,bhnd->bhmn", q.float(), k.float()) * scale
    attn   = torch.softmax(scores, dim=-1)
    return torch.einsum("bhmn,bhnd->bhmd", attn, v.float()).half()
