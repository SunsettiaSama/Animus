"""
Fused accept / reject kernel for Speculative Decoding.

Theory
------
For each draft position i, the acceptance probability is:

    α_i = min(1,  p_i(d_i) / q_i(d_i))

where p_i is the target-model distribution and q_i is the draft-model
distribution at that position.  Working in log-space for numerical stability:

    log α_i = min(0,  log_p_i(d_i) − log_q_i(d_i))
    accept   = (uniform_sample < exp(log α_i))

Kernel inputs / outputs
-----------------------
Inputs (all pre-computed, passed as scalars per (batch, draft_position)):
    p_lp   : [B, k]  log P_target(draft_token)   (one scalar per position)
    q_lp   : [B, k]  log P_draft (draft_token)
    rand   : [B, k]  pre-sampled uniform ∈ [0, 1)

Output:
    accept : [B, k]  int32  (1 = accepted, 0 = rejected)

The first-rejection index and corrected-token sampling are handled in Python
after the kernel because k is small (4-8) and vocab sampling needs full logits.

Fusion benefit
--------------
Without this kernel the accept check requires a CPU round-trip:
  GPU → (p scalar, q scalar) → CPU → (alpha, rand compare) → CPU → GPU

With the kernel, the entire alpha computation and Bernoulli test stay on GPU.
For large batch sizes this saves significant latency per speculative round.
"""

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
# Triton kernel
# ─────────────────────────────────────────────────────────────────────────────

if _TRITON_AVAILABLE:
    @triton.jit
    def _accept_kernel(
        p_lp_ptr,       # [B, k]  float32
        q_lp_ptr,       # [B, k]  float32
        rand_ptr,       # [B, k]  float32
        accept_ptr,     # [B, k]  int32   (output)
        stride_b,       # stride along batch dimension (= k)
    ):
        b = tl.program_id(0)
        i = tl.program_id(1)

        off = b * stride_b + i

        p_lp = tl.load(p_lp_ptr  + off).to(tl.float32)
        q_lp = tl.load(q_lp_ptr  + off).to(tl.float32)
        r    = tl.load(rand_ptr   + off).to(tl.float32)

        # log α = min(0, p_lp − q_lp)   →   α = min(1, p/q)
        log_alpha = tl.minimum(0.0, p_lp - q_lp)
        alpha     = tl.exp(log_alpha)

        accepted  = (r < alpha).to(tl.int32)
        tl.store(accept_ptr + off, accepted)


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch fallback — identical semantics
# ─────────────────────────────────────────────────────────────────────────────

def _accept_pytorch(
    p_lp:  torch.Tensor,   # [B, k]
    q_lp:  torch.Tensor,   # [B, k]
    rand:  torch.Tensor,   # [B, k]
) -> torch.Tensor:
    log_alpha = torch.minimum(torch.zeros_like(p_lp), p_lp - q_lp)
    alpha     = log_alpha.exp()
    return (rand < alpha).to(torch.int32)


# ─────────────────────────────────────────────────────────────────────────────
# Unified public API
# ─────────────────────────────────────────────────────────────────────────────

def accept_check(
    p_lp:  torch.Tensor,              # [B, k]  log P_target(draft_token)
    q_lp:  torch.Tensor,              # [B, k]  log P_draft (draft_token)
    rand:  torch.Tensor | None = None,  # [B, k]  pre-sampled; generated if None
) -> tuple[torch.Tensor, torch.Tensor]:
    """Run the fused accept/reject test.

    Returns
    -------
    accept_mask : [B, k]   int32  — 1 if token accepted, 0 if rejected
    first_reject: [B]      int64  — index of first rejection per sequence
                                    (equals k if all k tokens were accepted)
    """
    B, k = p_lp.shape

    if rand is None:
        rand = torch.rand_like(p_lp)

    p_lp = p_lp.contiguous().float()
    q_lp = q_lp.contiguous().float()
    rand = rand.contiguous().float()

    accept = torch.empty(B, k, dtype=torch.int32, device=p_lp.device)

    if _TRITON_AVAILABLE and p_lp.is_cuda:
        grid = (B, k)
        _accept_kernel[grid](p_lp, q_lp, rand, accept, stride_b=k)
    else:
        accept = _accept_pytorch(p_lp, q_lp, rand)

    # Find first rejection index per sequence (k = "all accepted")
    any_reject = accept.eq(0)
    first_reject = torch.where(
        any_reject.any(dim=1),
        any_reject.float().argmax(dim=1),
        torch.full((B,), k, dtype=torch.long, device=p_lp.device),
    )

    return accept, first_reject


def sample_corrected(
    target_logits:  torch.Tensor,   # [V]  full logits at the rejection position
    draft_log_prob: torch.Tensor,   # [V]  log probs from draft model at same position
) -> int:
    """Sample one token from the corrected distribution max(0, p − q) / Z.

    If the adjusted distribution is numerically zero (p ≈ q everywhere),
    falls back to sampling from p directly.
    """
    p   = torch.softmax(target_logits.float(), dim=-1)
    q   = draft_log_prob.float().exp()
    adj = (p - q).clamp(min=0.0)
    Z   = adj.sum()

    if Z.item() < 1e-8:
        return torch.multinomial(p, num_samples=1).item()

    return torch.multinomial(adj / Z, num_samples=1).item()
