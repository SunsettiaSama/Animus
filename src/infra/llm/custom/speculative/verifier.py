"""
Verifier — accept/reject logic for Speculative Decoding.

Wraps the fused accept kernel and the corrected-token sampler into a single
object that takes target-model logits + draft-model log-probs and returns
the number of accepted tokens and the corrected token for each sequence.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from infra.llm.custom.speculative.kernel.accept import accept_check, sample_corrected


@dataclass
class VerifyResult:
    """Output of one verify round for a batch of sequences."""
    num_accepted:      torch.Tensor   # [B]  int64 — tokens accepted (0..k)
    corrected_tokens:  torch.Tensor   # [B]  int64 — token at first rejection / bonus
    accept_mask:       torch.Tensor   # [B, k] int32 — per-position accept flag


class Verifier:
    """Accept/reject engine for one speculative round.

    Usage
    -----
    verifier = Verifier()
    result   = verifier.verify(target_logits, draft_log_probs, draft_ids)

    Parameters to verify()
    ----------------------
    target_logits  : [B, k+1, V]
        Target-model logits at draft positions n+1..n+k, plus an extra
        position n+k+1 used when *all* k tokens are accepted (the bonus token).
    draft_log_probs: [B, k, V]
        Draft-model log-probabilities at each of the k draft positions.
        Must be log_softmax output (not raw logits).
    draft_ids      : [B, k]  int64
        Token IDs sampled by the draft model.
    """

    def verify(
        self,
        target_logits:   torch.Tensor,   # [B, k+1, V]
        draft_log_probs: torch.Tensor,   # [B, k,   V]
        draft_ids:       torch.Tensor,   # [B, k]
    ) -> VerifyResult:
        B, k, V = draft_log_probs.shape
        device   = target_logits.device

        # ── Step 1: Extract the scalar log-prob of each draft token ──────────
        # p_lp[b, i] = log P_target(draft_ids[b,i])  at position i
        # q_lp[b, i] = log P_draft (draft_ids[b,i])  at position i

        target_log_probs = torch.log_softmax(target_logits[:, :k, :].float(), dim=-1)

        idx = draft_ids.unsqueeze(-1)                         # [B, k, 1]
        p_lp = target_log_probs.gather(dim=2, index=idx).squeeze(-1)   # [B, k]
        q_lp = draft_log_probs.gather( dim=2, index=idx).squeeze(-1)   # [B, k]

        # ── Step 2: Fused accept/reject kernel ───────────────────────────────
        accept_mask, first_reject = accept_check(p_lp, q_lp)
        # accept_mask : [B, k]   int32
        # first_reject: [B]      int64   (k = all accepted)

        # ── Step 3: Sample corrected token for each sequence ─────────────────
        corrected = torch.zeros(B, dtype=torch.long, device=device)

        for b in range(B):
            j = first_reject[b].item()

            if j == k:
                # All k draft tokens accepted — use the bonus position (k+1-th
                # output of the target model) to generate one more token for free.
                corrected[b] = torch.multinomial(
                    torch.softmax(target_logits[b, k].float(), dim=-1),
                    num_samples=1,
                ).item()
            else:
                # Sample from the adjusted distribution max(0, p_j − q_j) / Z
                corrected[b] = sample_corrected(
                    target_logits  [b, j],
                    draft_log_probs[b, j],
                )

        return VerifyResult(
            num_accepted     = first_reject,   # accepted count = first rejection index
            corrected_tokens = corrected,
            accept_mask      = accept_mask,
        )
