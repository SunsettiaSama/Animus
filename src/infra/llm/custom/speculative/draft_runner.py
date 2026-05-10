"""
DraftRunner — small-model decode loop for Speculative Decoding.

Runs k sequential decode steps with the draft model, collecting both the
sampled token IDs and the full log-probability distributions needed by the
Verifier for the acceptance check.

Model interface
---------------
The draft model is supplied as a callable with the signature:

    step_fn(token_ids: Tensor [B], seq_ids: list[int]) -> Tensor [B, vocab_size]

The function receives the current token for each sequence and returns logits
over the vocabulary.  The caller is responsible for maintaining the model's
KV cache (BlockSpaceManager) externally; this class only handles the
token-level sampling loop.

Rollback
--------
After the Verifier determines how many tokens to keep, call rollback() to
truncate the draft model's KV cache to the accepted prefix so that the next
draft round starts from the correct position.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch

from infra.llm.custom.block_space_manager.block_manager import BlockSpaceManager


@dataclass
class DraftOutput:
    """Collected output of one k-step draft phase."""
    draft_ids:       torch.Tensor   # [B, k]    int64
    draft_log_probs: torch.Tensor   # [B, k, V] float32


class DraftRunner:
    """Runs k decode steps with the draft (small) model.

    Parameters
    ----------
    step_fn   : callable(token_ids [B], seq_ids) -> logits [B, V]
                Wraps one decode step of the draft model.
    block_mgr : BlockSpaceManager for the draft model's KV cache.
    k         : number of draft tokens to generate per round.
    """

    def __init__(
        self,
        step_fn:   object,            # callable
        block_mgr: BlockSpaceManager,
        k:         int,
    ) -> None:
        self._step     = step_fn
        self._mgr      = block_mgr
        self._k        = k

    # ── Public API ────────────────────────────────────────────────────────────

    def draft(
        self,
        seq_ids:      list[int],
        current_ids:  torch.Tensor,   # [B]  the last accepted token per sequence
    ) -> DraftOutput:
        """Generate k draft tokens for each sequence.

        Runs the draft model k times autoregressively.  At each step:
          1. Feed the current token to step_fn → logits [B, V]
          2. Compute log_softmax → log_probs [B, V]
          3. Sample the next token from the distribution
          4. Append the token to the draft model's KV (via step_fn side effect)
          5. Advance the BlockSpaceManager token count

        Returns DraftOutput with draft_ids [B, k] and draft_log_probs [B, k, V].
        """
        B = len(seq_ids)
        device = current_ids.device

        all_ids:       list[torch.Tensor] = []   # each [B]
        all_log_probs: list[torch.Tensor] = []   # each [B, V]

        token = current_ids.clone()   # [B]

        for _ in range(self._k):
            logits    = self._step(token, seq_ids)             # [B, V]
            log_probs = torch.log_softmax(logits.float(), dim=-1)   # [B, V]
            token     = torch.multinomial(log_probs.exp(), num_samples=1).squeeze(1)  # [B]

            all_ids.append(token)
            all_log_probs.append(log_probs)

            # Advance BlockSpaceManager token counter (KV written by step_fn)
            for b, seq_id in enumerate(seq_ids):
                self._mgr.append_token(seq_id)

        draft_ids       = torch.stack(all_ids,       dim=1)   # [B, k]
        draft_log_probs = torch.stack(all_log_probs, dim=1)   # [B, k, V]

        return DraftOutput(draft_ids=draft_ids, draft_log_probs=draft_log_probs)

    def rollback(self, seq_ids: list[int], keep_counts: torch.Tensor) -> None:
        """Truncate each sequence's draft KV cache to keep_counts[b] new tokens.

        keep_counts[b] is the number of draft tokens to retain (0..k).
        The BlockSpaceManager's num_tokens for seq_ids[b] is set to
        (original_len + keep_counts[b]).

        Called after Verifier.verify() to discard rejected draft tokens so that
        the next draft round starts from the correct position.
        """
        for b, seq_id in enumerate(seq_ids):
            state = self._mgr._seqs[seq_id]
            # keep_counts[b] accepted tokens + 1 corrected token
            target_len = state.num_tokens - (self._k - int(keep_counts[b].item()))
            if target_len < state.num_tokens:
                self._mgr.rollback(seq_id, target_len)

    def append_token(self, seq_ids: list[int], token_ids: torch.Tensor) -> None:
        """Write one confirmed token per sequence into the draft KV cache.

        Used to synchronise the draft model after the corrected token is
        accepted, so that the next draft round starts from the right context.

        token_ids: [B]
        """
        self._step(token_ids, seq_ids)
        for seq_id in seq_ids:
            self._mgr.append_token(seq_id)
