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
    """Paged attention for a single transformer layer.

    Owns a view into the global KV block pool for this layer and delegates
    to the appropriate kernel (Triton on Linux, PyTorch on Windows).
    The BlockSpaceManager lives in the Worker — this layer receives it at
    construction time, mirroring vLLM's ModelRunner pattern.
    """

    def __init__(
        self,
        layer_id:  int,
        num_heads: int,
        head_dim:  int,
        page_size: int,
        pool:      BlockPool,
        block_mgr: BlockSpaceManager,
    ) -> None:
        super().__init__()
        self.layer_id  = layer_id
        self.num_heads = num_heads
        self.head_dim  = head_dim
        self.page_size = page_size
        self.scale     = 1.0 / math.sqrt(head_dim)
        self._pool     = pool
        self._mgr      = block_mgr

        # Slice this layer's view — [num_blocks, H, page_size, D]  (no copy)
        self._k_layer = pool.k_pool[:, layer_id, :, :, :]
        self._v_layer = pool.v_pool[:, layer_id, :, :, :]

    def kv_write(self, k: torch.Tensor, v: torch.Tensor, seq_id: int) -> None:
        """Scatter all prefill K/V tokens into their assigned physical blocks.

        k, v: [num_tokens, H, D]
        """
        state = self._mgr._seqs[seq_id]
        kv_write(k, v, self._k_layer, self._v_layer,
                 state.physical_blocks, self.page_size)

    def kv_append(
        self,
        k:       torch.Tensor,   # [B, H, 1, D]
        v:       torch.Tensor,
        seq_ids: list[int],
    ) -> None:
        """Write one new decode-step token per sequence into the pool."""
        for b, seq_id in enumerate(seq_ids):
            state     = self._mgr._seqs[seq_id]
            token_pos = state.num_tokens - 1   # already incremented by append_token()
            phys_blk  = state.physical_blocks[-1]
            slot      = token_pos % self.page_size
            self._k_layer[phys_blk, :, slot, :] = k[b, :, 0, :]
            self._v_layer[phys_blk, :, slot, :] = v[b, :, 0, :]

    def forward(self, q: torch.Tensor, seq_ids: list[int]) -> torch.Tensor:
        """Run paged attention for a batch.

        q: [B, H, Sq, D]
        Returns output of same shape.

        Dispatches to FA2 CUDA kernel → Triton → PyTorch fallback via cuda_attn.
        """
        block_table, context_lens = self._mgr.build_block_table(
            seq_ids, device=str(q.device)
        )
        return paged_attn2_fwd(
            q, self._k_layer, self._v_layer,
            block_table, context_lens,
        )


class ToyTransformerLayer(nn.Module):
    """Minimal transformer block with paged KV cache.

    Demonstrates how a real model layer integrates PagedAttentionLayer:
    a standard QKV linear projection feeds into paged attention, with
    the KV cache written/appended through the BlockSpaceManager.
    """

    def __init__(
        self,
        layer_id:  int,
        hidden:    int,
        num_heads: int,
        page_size: int,
        pool:      BlockPool,
        block_mgr: BlockSpaceManager,
    ) -> None:
        super().__init__()
        assert hidden % num_heads == 0
        self.num_heads = num_heads
        self.head_dim  = hidden // num_heads
        self.hidden    = hidden

        self.qkv_proj  = nn.Linear(hidden, hidden * 3, bias=False, dtype=torch.float16)
        self.o_proj    = nn.Linear(hidden, hidden,     bias=False, dtype=torch.float16)
        self.paged_attn = PagedAttentionLayer(
            layer_id, num_heads, self.head_dim, page_size, pool, block_mgr
        )

    def _split_qkv(self, qkv: torch.Tensor):
        B, Sq, _ = qkv.shape
        qkv = qkv.view(B, Sq, 3, self.num_heads, self.head_dim)
        qkv = qkv.permute(2, 0, 3, 1, 4)   # [3, B, H, Sq, D]
        return qkv[0], qkv[1], qkv[2]

    def prefill(self, x: torch.Tensor, seq_ids: list[int]) -> torch.Tensor:
        B, Sq, _ = x.shape
        qkv      = self.qkv_proj(x)
        q, k, v  = self._split_qkv(qkv)

        for b, seq_id in enumerate(seq_ids):
            actual_len = self.paged_attn._mgr._seqs[seq_id].num_tokens
            self.paged_attn.kv_write(
                k[b, :, :actual_len, :].permute(1, 0, 2).contiguous(),
                v[b, :, :actual_len, :].permute(1, 0, 2).contiguous(),
                seq_id,
            )

        attn_out = self.paged_attn.forward(q, seq_ids)
        attn_out = attn_out.permute(0, 2, 1, 3).contiguous().view(B, Sq, -1)
        return self.o_proj(attn_out)

    def decode_step(self, x: torch.Tensor, seq_ids: list[int]) -> torch.Tensor:
        B, _, _ = x.shape
        qkv     = self.qkv_proj(x)
        q, k, v = self._split_qkv(qkv)

        for b, seq_id in enumerate(seq_ids):
            self.paged_attn._mgr.append_token(seq_id)
        self.paged_attn.kv_append(k, v, seq_ids)

        attn_out = self.paged_attn.forward(q, seq_ids)
        attn_out = attn_out.permute(0, 2, 1, 3).contiguous().view(B, 1, -1)
        return self.o_proj(attn_out)
