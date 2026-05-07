"""
Flash Attention + Paged Attention Triton demo
=============================================

Structural relationship
-----------------------
  Flash Attention:  K/V ∈ contiguous [B, H, N, D] tensor;
                    each Triton tile walks a fixed stride.
  Paged Attention:  K/V are split into fixed-size "pages" stored at
                    arbitrary physical addresses.  A block_table
                    [batch, logical_page_idx] → phys_page_id maps
                    logical order to physical storage at kernel time.

The two kernels below share an identical online-softmax accumulation body.
The ONLY difference is the two lines that compute the K/V base pointer:
  flash  →  K_ptr + n_start * stride_kn
  paged  →  K_cache + block_table[batch, page_idx] * stride_kb
"""

import math
import torch
import triton
import triton.language as tl


# ─────────────────────────────────────────────────────────────────────────────
# Kernel 1 – Flash Attention (contiguous KV)
# ─────────────────────────────────────────────────────────────────────────────
# Grid: (ceil(Sq/BLOCK_M), H, B)
# Each program owns one [BLOCK_M, D] output tile; it streams over all KV tiles.
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
    q_offs  = q_start + tl.arange(0, BLOCK_M)   # [BLOCK_M]
    d_offs  = tl.arange(0, HEAD_DIM)             # [HEAD_DIM]

    Q_ptr = Q + batch_id * stride_qb + head_id * stride_qh
    q = tl.load(
        Q_ptr + q_offs[:, None] * stride_qm + d_offs[None, :] * stride_qd,
        mask=q_offs[:, None] < seqlen_q,
        other=0.0,
    ).to(tl.float32)                             # [BLOCK_M, HEAD_DIM]

    # Online softmax state (Dao et al. 2022, §3.1)
    m_i = tl.full([BLOCK_M], float("-inf"), dtype=tl.float32)   # running row max
    l_i = tl.zeros([BLOCK_M], dtype=tl.float32)                  # running sum(exp)
    acc = tl.zeros([BLOCK_M, HEAD_DIM], dtype=tl.float32)        # running weighted V

    K_ptr = K + batch_id * stride_kb + head_id * stride_kh
    V_ptr = V + batch_id * stride_vb + head_id * stride_vh

    # ── KV tiling loop ───────────────────────────────────────────────────────
    # Each iteration loads one [HEAD_DIM, BLOCK_N] K tile and one
    # [BLOCK_N, HEAD_DIM] V tile from *contiguous* memory.
    for n_start in range(0, seqlen_k, BLOCK_N):
        n_offs = n_start + tl.arange(0, BLOCK_N)

        k = tl.load(                             # [HEAD_DIM, BLOCK_N]
            K_ptr + d_offs[:, None] * stride_kd + n_offs[None, :] * stride_kn,
            mask=n_offs[None, :] < seqlen_k,
            other=0.0,
        ).to(tl.float32)

        v = tl.load(                             # [BLOCK_N, HEAD_DIM]
            V_ptr + n_offs[:, None] * stride_vn + d_offs[None, :] * stride_vd,
            mask=n_offs[:, None] < seqlen_k,
            other=0.0,
        ).to(tl.float32)

        scores = tl.dot(q, k) * scale            # [BLOCK_M, BLOCK_N]
        scores = tl.where(n_offs[None, :] < seqlen_k, scores, float("-inf"))

        # Online softmax rescale
        m_new      = tl.maximum(m_i, tl.max(scores, axis=1))
        exp_scores = tl.exp(scores - m_new[:, None])
        rescale    = tl.exp(m_i - m_new)
        l_i = l_i * rescale + tl.sum(exp_scores, axis=1)
        acc = acc * rescale[:, None] + tl.dot(exp_scores, v)
        m_i = m_new

    out = (acc / l_i[:, None]).to(tl.float16)

    O_ptr = Out + batch_id * stride_ob + head_id * stride_oh
    tl.store(
        O_ptr + q_offs[:, None] * stride_om + d_offs[None, :] * stride_od,
        out,
        mask=q_offs[:, None] < seqlen_q,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Kernel 2 – Paged Attention (non-contiguous KV via block_table)
# ─────────────────────────────────────────────────────────────────────────────
# KV cache layout: [num_phys_blocks, H, PAGE_SIZE, HEAD_DIM]
#   stride_kb = H * PAGE_SIZE * HEAD_DIM   (physical block stride)
#   stride_kh = PAGE_SIZE * HEAD_DIM
#   stride_kp = HEAD_DIM                   (slot / token-position stride)
#   stride_kd = 1
#
# block_table: [B, max_pages_per_seq]
#   block_table[b, i] = physical block id for logical page i of sequence b
#
# context_lens: [B]  – actual KV length (may be < max_pages*PAGE_SIZE)
#
# Grid: same as flash attention: (ceil(Sq/BLOCK_M), H, B)
@triton.jit
def _paged_attn_fwd(
    Q,                                        # [B, H, Sq, D]
    K_cache, V_cache,                         # [num_phys_blocks, H, PAGE_SIZE, D]
    block_table,                              # [B, max_pages_per_seq]
    context_lens,                             # [B]
    Out,                                      # [B, H, Sq, D]
    stride_qb, stride_qh, stride_qm, stride_qd,
    stride_kb, stride_kh, stride_kp, stride_kd,  # b = physical block
    stride_vb, stride_vh, stride_vp, stride_vd,
    stride_ob, stride_oh, stride_om, stride_od,
    stride_btb, stride_btn,                       # block_table strides
    seqlen_q,
    scale,
    HEAD_DIM:   tl.constexpr,
    BLOCK_M:    tl.constexpr,
    PAGE_SIZE:  tl.constexpr,   # tokens per page == BLOCK_N in flash attn
    MAX_PAGES:  tl.constexpr,   # upper-bound loop trip count
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
        mask=q_offs[:, None] < seqlen_q,
        other=0.0,
    ).to(tl.float32)

    ctx_len = tl.load(context_lens + batch_id)

    m_i = tl.full([BLOCK_M], float("-inf"), dtype=tl.float32)
    l_i = tl.zeros([BLOCK_M], dtype=tl.float32)
    acc = tl.zeros([BLOCK_M, HEAD_DIM], dtype=tl.float32)

    page_offs = tl.arange(0, PAGE_SIZE)          # [PAGE_SIZE]

    # ── Paged KV loop ────────────────────────────────────────────────────────
    # Structurally identical to flash attention's KV loop.
    # The critical difference: K and V are fetched through the block_table
    # instead of from a contiguous stride, enabling arbitrary physical layout.
    for page_idx in range(0, MAX_PAGES):
        # Gate: skip pages beyond this sequence's actual length
        kv_start = page_idx * PAGE_SIZE
        valid_page = kv_start < ctx_len

        # Indirect memory access: block_table[batch, page_idx] → physical block
        phys_block = tl.load(
            block_table + batch_id * stride_btb + page_idx * stride_btn,
            mask=valid_page,
            other=0,
        )
        kv_offs = kv_start + page_offs           # logical KV positions [PAGE_SIZE]

        # Fetch K page as [HEAD_DIM, PAGE_SIZE] from physical address
        K_page = K_cache + phys_block * stride_kb + head_id * stride_kh
        k = tl.load(
            K_page + d_offs[:, None] * stride_kd + page_offs[None, :] * stride_kp,
            mask=(kv_offs[None, :] < ctx_len) & valid_page,
            other=0.0,
        ).to(tl.float32)

        # Fetch V page as [PAGE_SIZE, HEAD_DIM] from physical address
        V_page = V_cache + phys_block * stride_vb + head_id * stride_vh
        v = tl.load(
            V_page + page_offs[:, None] * stride_vp + d_offs[None, :] * stride_vd,
            mask=(kv_offs[:, None] < ctx_len) & valid_page,
            other=0.0,
        ).to(tl.float32)

        # ── Exact same online-softmax body as flash attention ────────────────
        scores = tl.dot(q, k) * scale
        scores = tl.where(
            (kv_offs[None, :] < ctx_len) & valid_page, scores, float("-inf")
        )
        m_new      = tl.maximum(m_i, tl.max(scores, axis=1))
        exp_scores = tl.exp(scores - m_new[:, None])
        rescale    = tl.exp(m_i - m_new)
        l_i = l_i * rescale + tl.sum(exp_scores, axis=1)
        acc = acc * rescale[:, None] + tl.dot(exp_scores, v)
        m_i = m_new

    out = (acc / l_i[:, None]).to(tl.float16)

    O_ptr = Out + batch_id * stride_ob + head_id * stride_oh
    tl.store(
        O_ptr + q_offs[:, None] * stride_om + d_offs[None, :] * stride_od,
        out,
        mask=q_offs[:, None] < seqlen_q,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Python wrappers
# ─────────────────────────────────────────────────────────────────────────────

def flash_attn(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
    B, H, Sq, D = q.shape
    _, _, Sk, _  = k.shape
    assert q.is_cuda and k.is_cuda and v.is_cuda
    assert q.dtype == k.dtype == v.dtype == torch.float16

    BLOCK_M = 16
    BLOCK_N = 16
    scale   = 1.0 / math.sqrt(D)
    out     = torch.empty_like(q)

    grid = (triton.cdiv(Sq, BLOCK_M), H, B)
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


def _build_paged_kv(k: torch.Tensor, v: torch.Tensor, page_size: int):
    """Scatter contiguous [B, H, N, D] K/V into a paged KV cache.

    Returns
    -------
    k_cache    : [num_phys_blocks, H, PAGE_SIZE, D]
    v_cache    : [num_phys_blocks, H, PAGE_SIZE, D]
    block_table: [B, max_pages]  int32
    context_lens: [B]  int32
    """
    B, H, N, D = k.shape
    max_pages   = math.ceil(N / page_size)
    num_blocks  = B * max_pages

    k_cache = torch.zeros(num_blocks, H, page_size, D, device=k.device, dtype=k.dtype)
    v_cache = torch.zeros(num_blocks, H, page_size, D, device=k.device, dtype=k.dtype)
    block_table = torch.zeros(B, max_pages, device=k.device, dtype=torch.int32)

    for b in range(B):
        for p in range(max_pages):
            phys = b * max_pages + p
            block_table[b, p] = phys
            tok_start = p * page_size
            tok_end   = min(tok_start + page_size, N)
            actual    = tok_end - tok_start
            # k[b, :, tok_start:tok_end, :] → k_cache[phys, :, :actual, :]
            k_cache[phys, :, :actual, :] = k[b, :, tok_start:tok_end, :]
            v_cache[phys, :, :actual, :] = v[b, :, tok_start:tok_end, :]

    context_lens = torch.full((B,), N, device=k.device, dtype=torch.int32)
    return k_cache, v_cache, block_table, context_lens


def paged_attn(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    page_size: int = 16,
) -> torch.Tensor:
    B, H, Sq, D = q.shape
    _, _, N,  _  = k.shape
    assert q.is_cuda and k.is_cuda and v.is_cuda
    assert q.dtype == k.dtype == v.dtype == torch.float16

    k_cache, v_cache, block_table, context_lens = _build_paged_kv(k, v, page_size)

    max_pages = block_table.shape[1]
    BLOCK_M   = 16
    scale     = 1.0 / math.sqrt(D)
    out       = torch.empty_like(q)

    grid = (triton.cdiv(Sq, BLOCK_M), H, B)
    _paged_attn_fwd[grid](
        q, k_cache, v_cache, block_table, context_lens, out,
        q.stride(0),       q.stride(1),       q.stride(2),       q.stride(3),
        k_cache.stride(0), k_cache.stride(1), k_cache.stride(2), k_cache.stride(3),
        v_cache.stride(0), v_cache.stride(1), v_cache.stride(2), v_cache.stride(3),
        out.stride(0),     out.stride(1),     out.stride(2),     out.stride(3),
        block_table.stride(0), block_table.stride(1),
        Sq, scale,
        HEAD_DIM=D, BLOCK_M=BLOCK_M, PAGE_SIZE=page_size, MAX_PAGES=max_pages,
    )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Reference: pure-PyTorch scaled dot-product attention
# ─────────────────────────────────────────────────────────────────────────────

def ref_attn(q, k, v):
    scale  = 1.0 / math.sqrt(q.shape[-1])
    # q,k,v: [B, H, S, D]
    scores = torch.einsum("bhmd,bhnd->bhmn", q.float(), k.float()) * scale
    attn   = torch.softmax(scores, dim=-1)
    return torch.einsum("bhmn,bhnd->bhmd", attn, v.float()).half()


# ─────────────────────────────────────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────────────────────────────────────

def main():
    torch.manual_seed(42)
    B, H, N, D = 2, 4, 64, 64
    PAGE_SIZE   = 16                       # must match what paged_attn() uses

    q = torch.randn(B, H, N, D, device="cuda", dtype=torch.float16)
    k = torch.randn(B, H, N, D, device="cuda", dtype=torch.float16)
    v = torch.randn(B, H, N, D, device="cuda", dtype=torch.float16)

    # ── Correctness check ────────────────────────────────────────────────────
    ref_out   = ref_attn(q, k, v)
    flash_out = flash_attn(q, k, v)
    paged_out = paged_attn(q, k, v, page_size=PAGE_SIZE)

    flash_err = (flash_out.float() - ref_out.float()).abs().max().item()
    paged_err = (paged_out.float() - ref_out.float()).abs().max().item()

    print(f"[correctness]  flash vs ref : max|Δ| = {flash_err:.5f}")
    print(f"[correctness]  paged vs ref : max|Δ| = {paged_err:.5f}")
    assert flash_err < 0.05, f"flash attention numerical error too large: {flash_err}"
    assert paged_err < 0.05, f"paged attention numerical error too large: {paged_err}"

    flash_paged_err = (flash_out.float() - paged_out.float()).abs().max().item()
    print(f"[correctness]  flash vs paged: max|Δ| = {flash_paged_err:.5f}")
    assert flash_paged_err < 0.02, f"flash/paged divergence: {flash_paged_err}"
    print("[correctness]  PASS ✓\n")

    # ── Timing ───────────────────────────────────────────────────────────────
    def bench(fn, label):
        ms = triton.testing.do_bench(fn, warmup=25, rep=100)
        print(f"[timing]  {label:<22s}: {ms:.3f} ms")

    bench(lambda: flash_attn(q, k, v),                    "Flash Attention")
    bench(lambda: paged_attn(q, k, v, page_size=PAGE_SIZE), "Paged Attention")
    bench(lambda: ref_attn(q, k, v),                      "PyTorch reference")

    # ── Structural summary ───────────────────────────────────────────────────
    max_pages = math.ceil(N / PAGE_SIZE)
    print(f"""
[architecture]
  Sequence length : {N} tokens
  Page size       : {PAGE_SIZE} tokens/page  ({max_pages} pages per seq)
  Physical blocks : {B * max_pages}  (batch={B}, pages_per_seq={max_pages})

  Flash Attention inner loop
    for n_start in range(0, {N}, {PAGE_SIZE}):
        k = K[batch, head, n_start : n_start+{PAGE_SIZE}, :]   # contiguous stride
        v = V[batch, head, n_start : n_start+{PAGE_SIZE}, :]
        <online-softmax update>

  Paged Attention inner loop
    for page_idx in range(0, {max_pages}):
        phys = block_table[batch, page_idx]              # indirection ← only change
        k = K_cache[phys, head, :, :]                    # non-contiguous page
        v = V_cache[phys, head, :, :]
        <online-softmax update>   ← identical to flash attention
""")


if __name__ == "__main__":
    main()
