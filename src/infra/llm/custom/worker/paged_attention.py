from __future__ import annotations

import math
from typing import TYPE_CHECKING

import torch
import torch.nn as nn

from infra.llm.custom.worker.kernel.kv_write import kv_write
from infra.llm.custom.worker.kernel.cuda_attn import paged_attn2_fwd

if TYPE_CHECKING:
    from infra.llm.custom.block_space_manager.block_manager import BlockPool, BlockSpaceManager


class PagedAttentionLayer(nn.Module):
    """Paged attention for a single transformer layer, GQA-aware.

    Owns a view into the global KV block pool for this layer and delegates
    to the appropriate kernel (CUDA C++ > Triton > PyTorch).

    Parameters
    ----------
    num_q_heads  : number of query heads  (H_q)
    num_kv_heads : number of KV heads     (H_kv); equals H_q for MHA
    group_size   : H_q // H_kv  (computed automatically)
    """

    def __init__(
        self,
        layer_id:     int,
        num_q_heads:  int,
        num_kv_heads: int,
        head_dim:     int,
        page_size:    int,
        pool:         BlockPool,
        block_mgr:    BlockSpaceManager,
    ) -> None:
        super().__init__()
        assert num_q_heads % num_kv_heads == 0, \
            f"num_q_heads ({num_q_heads}) must be divisible by num_kv_heads ({num_kv_heads})"

        self.layer_id     = layer_id
        self.num_q_heads  = num_q_heads
        self.num_kv_heads = num_kv_heads
        self.group_size   = num_q_heads // num_kv_heads   # 1 for MHA
        self.head_dim     = head_dim
        self.page_size    = page_size
        self.scale        = 1.0 / math.sqrt(head_dim)
        self._pool        = pool
        self._mgr         = block_mgr

        # Slice this layer's KV view — [num_blocks, H_kv, page_size, D] (no copy)
        self._k_layer = pool.k_pool[:, layer_id, :, :, :]
        self._v_layer = pool.v_pool[:, layer_id, :, :, :]

    def kv_write(self, k: torch.Tensor, v: torch.Tensor, seq_id: int) -> None:
        """Scatter all prefill K/V tokens into their assigned physical blocks.

        k, v: [num_tokens, H_kv, D]
        """
        state = self._mgr._seqs[seq_id]
        kv_write(k, v, self._k_layer, self._v_layer,
                 state.physical_blocks, self.page_size)

    def kv_append(
        self,
        k:       torch.Tensor,   # [B, H_kv, 1, D]
        v:       torch.Tensor,
        seq_ids: list[int],
    ) -> None:
        """Write one new decode-step token per sequence into the pool."""
        for b, seq_id in enumerate(seq_ids):
            state     = self._mgr._seqs[seq_id]
            token_pos = state.num_tokens - 1
            phys_blk  = state.physical_blocks[-1]
            slot      = token_pos % self.page_size
            self._k_layer[phys_blk, :, slot, :] = k[b, :, 0, :]
            self._v_layer[phys_blk, :, slot, :] = v[b, :, 0, :]

    def forward(self, q: torch.Tensor, seq_ids: list[int]) -> torch.Tensor:
        """Run paged attention for a batch.

        q: [B, H_q, Sq, D]
        Returns output of same shape.

        Dispatches to FA2 CUDA kernel → Triton → PyTorch fallback via cuda_attn.
        """
        block_table, context_lens = self._mgr.build_block_table(
            seq_ids, device=str(q.device)
        )
        return paged_attn2_fwd(
            q, self._k_layer, self._v_layer,
            block_table, context_lens,
            group_size=self.group_size,
        )


class ToyTransformerLayer(nn.Module):
    """Minimal transformer block with paged KV cache, GQA-aware.

    Uses separate Q and KV projections to support GQA/MQA.
    For MHA pass num_kv_heads == num_q_heads (or omit; defaults to MHA).
    """

    def __init__(
        self,
        layer_id:     int,
        hidden:       int,
        num_q_heads:  int,
        page_size:    int,
        pool:         BlockPool,
        block_mgr:    BlockSpaceManager,
        num_kv_heads: int | None = None,   # None → MHA (= num_q_heads)
    ) -> None:
        super().__init__()
        num_kv_heads = num_kv_heads or num_q_heads
        assert hidden % num_q_heads == 0
        assert num_q_heads % num_kv_heads == 0

        self.num_q_heads  = num_q_heads
        self.num_kv_heads = num_kv_heads
        self.head_dim     = hidden // num_q_heads
        self.hidden       = hidden

        q_dim  = num_q_heads  * self.head_dim
        kv_dim = num_kv_heads * self.head_dim

        self.q_proj   = nn.Linear(hidden, q_dim,      bias=False, dtype=torch.float16)
        self.kv_proj  = nn.Linear(hidden, kv_dim * 2, bias=False, dtype=torch.float16)
        self.o_proj   = nn.Linear(q_dim,  hidden,     bias=False, dtype=torch.float16)

        self.paged_attn = PagedAttentionLayer(
            layer_id, num_q_heads, num_kv_heads,
            self.head_dim, page_size, pool, block_mgr,
        )

    def _split_q(self, x: torch.Tensor):
        """x: [B, S, hidden] → q: [B, H_q, S, D]"""
        B, S, _ = x.shape
        return self.q_proj(x).view(B, S, self.num_q_heads, self.head_dim).permute(0, 2, 1, 3)

    def _split_kv(self, x: torch.Tensor):
        """x: [B, S, hidden] → k, v each [B, H_kv, S, D]"""
        B, S, _ = x.shape
        kv = self.kv_proj(x).view(B, S, 2, self.num_kv_heads, self.head_dim)
        kv = kv.permute(2, 0, 3, 1, 4)   # [2, B, H_kv, S, D]
        return kv[0], kv[1]

    def prefill(self, x: torch.Tensor, seq_ids: list[int]) -> torch.Tensor:
        B, Sq, _ = x.shape
        q        = self._split_q(x)           # [B, H_q,  Sq, D]
        k, v     = self._split_kv(x)          # [B, H_kv, Sq, D]

        for b, seq_id in enumerate(seq_ids):
            actual_len = self.paged_attn._mgr._seqs[seq_id].num_tokens
            self.paged_attn.kv_write(
                k[b, :, :actual_len, :].permute(1, 0, 2).contiguous(),   # [actual_len, H_kv, D]
                v[b, :, :actual_len, :].permute(1, 0, 2).contiguous(),
                seq_id,
            )

        attn_out = self.paged_attn.forward(q, seq_ids)                   # [B, H_q, Sq, D]
        attn_out = attn_out.permute(0, 2, 1, 3).contiguous().view(B, Sq, -1)
        return self.o_proj(attn_out)

    def decode_step(self, x: torch.Tensor, seq_ids: list[int]) -> torch.Tensor:
        B, _, _ = x.shape
        q       = self._split_q(x)    # [B, H_q,  1, D]
        k, v    = self._split_kv(x)   # [B, H_kv, 1, D]

        for b, seq_id in enumerate(seq_ids):
            self.paged_attn._mgr.append_token(seq_id)
        self.paged_attn.kv_append(k, v, seq_ids)

        attn_out = self.paged_attn.forward(q, seq_ids)
        attn_out = attn_out.permute(0, 2, 1, 3).contiguous().view(B, 1, -1)
        return self.o_proj(attn_out)
