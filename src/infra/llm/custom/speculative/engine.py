"""
SpeculativeEngine — top-level orchestrator for Speculative Decoding.

One round of speculative decoding:

  ┌─ Draft phase ──────────────────────────────────────────────────────────┐
  │  Small model: k sequential decode steps                                │
  │  Saves:  draft_ids [B, k],  draft_log_probs [B, k, V]                 │
  │  Target KV cache: FROZEN                                               │
  └────────────────────────────────────────────────────────────────────────┘
  ┌─ Verify phase (batched causal prefill) ────────────────────────────────┐
  │  Large model: ONE prefill call over [d1 .. dk, d_bonus]  (Sq = k+1)   │
  │  Causal mask ensures position i sees only tokens 0 .. ctx+i            │
  │  Returns:  target_logits [B, k+1, V]                                   │
  │  Target KV cache: k+1 new entries written in a single pass             │
  └────────────────────────────────────────────────────────────────────────┘
  ┌─ Accept / Reject phase ────────────────────────────────────────────────┐
  │  Fused kernel: α_i = min(1, p_i/q_i),  Bernoulli test per position    │
  │  Find first rejection index j  (j=k ⇒ all accepted + bonus token)     │
  │  Sample corrected token t' from max(0, p_j − q_j) / Z                 │
  └────────────────────────────────────────────────────────────────────────┘
  ┌─ Rollback phase ───────────────────────────────────────────────────────┐
  │  Target model KV: truncate to n + j,  write K/V for t'                │
  │  Draft  model KV: truncate to n + j,  write K/V for t' (sync)         │
  └────────────────────────────────────────────────────────────────────────┘

Model interfaces
----------------
    target_step_fn(token_ids [B], seq_ids) -> logits [B, V]
        One decode step; writes K/V as a side effect.

    target_prefill_fn(token_ids [B, Sq], seq_ids, q_start_pos [B]) -> logits [B, Sq, V]
        Batched causal prefill; writes Sq K/V entries per sequence.
        q_start_pos[b] = number of context tokens before the first new token.
        If not provided, _target_verify falls back to k+1 sequential steps.

Theoretical guarantee
---------------------
The output distribution is identical to running the target model alone for
every token (Leviathan et al. 2023).  Speed-up:
  - Draft phase: k fast small-model steps
  - Verify phase: ONE batched prefill on the large model (high GPU utilisation)
  - Average accepted tokens per round = E[α] + 1 > 1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import torch

from infra.llm.custom.block_space_manager.block_manager import BlockSpaceManager
from infra.llm.custom.speculative.draft_runner import DraftRunner
from infra.llm.custom.speculative.verifier import Verifier, VerifyResult


# Single-token decode step: (token_ids [B], seq_ids) -> logits [B, V]
StepFn = Callable[[torch.Tensor, list[int]], torch.Tensor]

# Batched causal prefill: (token_ids [B,Sq], seq_ids, q_start_pos [B]) -> [B,Sq,V]
PrefillFn = Callable[[torch.Tensor, list[int], torch.Tensor], torch.Tensor]


@dataclass
class RoundResult:
    """Output of one speculative round for a batch of sequences."""
    # Tokens produced this round per sequence (accepted drafts + corrected token)
    new_tokens:    dict[int, list[int]]
    # Per-sequence accept counts (for monitoring / adaptive k)
    num_accepted:  dict[int, int]


class SpeculativeEngine:
    """Orchestrates draft → verify → accept/rollback for a batch.

    Parameters
    ----------
    draft_step_fn   : one decode step of the small (draft) model
    target_step_fn  : one decode step of the large (target) model
    draft_block_mgr : BlockSpaceManager for the draft model's KV cache
    target_block_mgr: BlockSpaceManager for the target model's KV cache
    k               : number of draft tokens per round
    """

    def __init__(
        self,
        draft_step_fn:      StepFn,
        target_step_fn:     StepFn,
        draft_block_mgr:    BlockSpaceManager,
        target_block_mgr:   BlockSpaceManager,
        k:                  int              = 4,
        target_prefill_fn:  PrefillFn | None = None,
    ) -> None:
        self._target_step    = target_step_fn
        self._target_prefill = target_prefill_fn   # optional batched-prefill path
        self._target_mgr     = target_block_mgr
        self._k              = k
        self._verifier       = Verifier()
        self._draft_runner   = DraftRunner(draft_step_fn, draft_block_mgr, k)

    # ── Public API ────────────────────────────────────────────────────────────

    def step(
        self,
        seq_ids:     list[int],
        current_ids: torch.Tensor,   # [B]  last confirmed token per sequence
    ) -> RoundResult:
        """Run one full speculative round and return the newly produced tokens.

        Each call to step() produces between 1 and k+1 tokens per sequence
        depending on how many draft tokens are accepted.
        """
        B = len(seq_ids)

        # ── 1. Draft phase ────────────────────────────────────────────────────
        draft_out = self._draft_runner.draft(seq_ids, current_ids)
        # draft_out.draft_ids:       [B, k]
        # draft_out.draft_log_probs: [B, k, V]

        # ── 2. Verify phase ───────────────────────────────────────────────────
        # Run k+1 incremental decode steps on the target model.
        # The first k steps verify each draft token; the (k+1)-th step gives
        # the "bonus" logits used when all k tokens are accepted.
        target_logits = self._target_verify(seq_ids, draft_out.draft_ids)
        # target_logits: [B, k+1, V]

        # ── 3. Accept / Reject (fused kernel) ────────────────────────────────
        result: VerifyResult = self._verifier.verify(
            target_logits,
            draft_out.draft_log_probs,
            draft_out.draft_ids,
        )

        # ── 4. Rollback both KV caches and collect output tokens ──────────────
        new_tokens:   dict[int, list[int]] = {}
        num_accepted: dict[int, int]       = {}

        for b, seq_id in enumerate(seq_ids):
            n_acc  = int(result.num_accepted[b].item())   # accepted draft count
            t_corr = int(result.corrected_tokens[b].item())

            # Accepted draft tokens + the corrected / bonus token
            accepted_draft = draft_out.draft_ids[b, :n_acc].tolist()
            produced       = accepted_draft + [t_corr]

            # Rollback target KV cache: keep the first n_acc draft entries,
            # discard the rest (k − n_acc), then write corrected token's K/V.
            self._target_rollback_and_append(seq_id, n_acc, t_corr, b)

            # Sync draft model: discard rejected tokens, append corrected token.
            self._draft_runner.rollback([seq_id], result.num_accepted[b:b+1])
            self._draft_runner.append_token(
                [seq_id],
                torch.tensor([t_corr], device=current_ids.device),
            )

            new_tokens[seq_id]   = produced
            num_accepted[seq_id] = n_acc

        return RoundResult(new_tokens=new_tokens, num_accepted=num_accepted)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _target_verify(
        self,
        seq_ids:   list[int],
        draft_ids: torch.Tensor,   # [B, k]
    ) -> torch.Tensor:
        """Verify draft tokens with the target model.

        Fast path (preferred): single batched causal prefill over all k+1 tokens.
          - Requires target_prefill_fn to be provided at construction.
          - GPU utilisation is ~k× higher than the sequential fallback.
          - q_start_pos[b] = context length before this verify round starts.

        Slow path (fallback): k+1 sequential single-token decode steps.
          - Used when target_prefill_fn is None.

        Returns target_logits [B, k+1, V].
        """
        B, k = draft_ids.shape
        device = draft_ids.device

        # ── Fast path: single batched causal prefill ──────────────────────────
        if self._target_prefill is not None:
            # Collect context lengths BEFORE writing any new KV entries.
            q_start = torch.tensor(
                [self._target_mgr._seqs[sid].num_tokens for sid in seq_ids],
                dtype=torch.long, device=device,
            )  # [B]

            # Allocate K/V slots for all k+1 tokens at once.
            for sid in seq_ids:
                for _ in range(k + 1):
                    self._target_mgr.append_token(sid)

            # One prefill call: attends to full context + newly allocated slots,
            # with per-row causal masking enforced by q_start_pos.
            # token_ids [B, k+1]: draft tokens + last draft repeated as "bonus" input.
            bonus_col = draft_ids[:, -1:]                          # [B, 1]
            tokens    = torch.cat([draft_ids, bonus_col], dim=1)   # [B, k+1]
            logits    = self._target_prefill(tokens, seq_ids, q_start)   # [B, k+1, V]
            return logits

        # ── Slow path: k+1 sequential decode steps ───────────────────────────
        all_logits: list[torch.Tensor] = []
        for i in range(k):
            token  = draft_ids[:, i]
            logits = self._target_step(token, seq_ids)
            all_logits.append(logits)
            for sid in seq_ids:
                self._target_mgr.append_token(sid)

        bonus_logits = self._target_step(draft_ids[:, -1], seq_ids)
        all_logits.append(bonus_logits)
        return torch.stack(all_logits, dim=1)

    def _target_rollback_and_append(
        self,
        seq_id:  int,
        n_acc:   int,
        t_corr:  int,
        b:       int,
    ) -> None:
        """Truncate the target KV cache to the accepted prefix, then append t'.

        After verify, the target KV cache has k new entries (draft tokens).
        We keep the first n_acc of them and discard the rest.
        Then we append the corrected token t' to complete the round.
        """
        state       = self._target_mgr._seqs[seq_id]
        current_len = state.num_tokens

        # current_len = original_context_len + k  (verify wrote k entries)
        # We want to keep: original_context_len + n_acc
        keep_len = current_len - (self._k - n_acc)
        if keep_len < current_len:
            self._target_mgr.rollback(seq_id, keep_len)

        # Append corrected token's K/V via one target decode step
        device     = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        token_tens = torch.tensor([t_corr], device=device)
        self._target_step(token_tens, [seq_id])
        self._target_mgr.append_token(seq_id)
