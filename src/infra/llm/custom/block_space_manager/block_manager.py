from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from infra.llm.custom.block_space_manager.profiler import PreallocConfig, ProfileResult


# ─────────────────────────────────────────────────────────────────────────────
# Block pool — pre-allocated GPU KV cache tensors
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BlockPool:
    """Two contiguous GPU tensors that hold the entire KV cache for all sequences.

    Layout: [num_blocks, num_layers, num_heads, page_size, head_dim]

    Placing num_layers as the second axis lets a single layer slice its view
    cheaply: k_pool[:, layer_id, ...] — no copy.
    """

    k_pool:      object    # torch.Tensor  (None in dry-run)
    v_pool:      object
    num_blocks:  int
    num_layers:  int
    num_heads:   int
    page_size:   int
    head_dim:    int
    dtype_bytes: int       # 2 for fp16 / bf16

    @property
    def bytes_per_block(self) -> int:
        return (
            self.num_layers * self.num_heads * self.page_size
            * self.head_dim * self.dtype_bytes * 2    # × 2 for K and V
        )

    @property
    def total_bytes(self) -> int:
        return self.num_blocks * self.bytes_per_block


def allocate_block_pool(
    profile:  ProfileResult,
    cfg:      PreallocConfig,
    dry_run:  bool = False,
) -> BlockPool:
    """Compute how many physical blocks fit in GPU memory, then pre-allocate them."""
    dtype_bytes = 2

    bytes_per_block = (
        profile.num_layers * profile.num_heads
        * cfg.page_size * profile.head_dim * dtype_bytes * 2
    )

    free_bytes   = profile.total_gpu_bytes - profile.reserved_bytes
    usable_bytes = int(free_bytes * cfg.gpu_memory_utilization)
    num_blocks   = max(1, usable_bytes // bytes_per_block)

    print(f"[alloc] bytes per block      : {bytes_per_block / 1024:.1f} KB")
    print(f"[alloc] usable memory        : {usable_bytes / 1024**3:.2f} GB")
    print(f"[alloc] num physical blocks  : {num_blocks}")
    print(f"[alloc] max tokens in pool   : {num_blocks * cfg.page_size:,}")

    if dry_run:
        print("[alloc] dry-run: skipping actual GPU allocation\n")
        return BlockPool(
            k_pool=None, v_pool=None,
            num_blocks=num_blocks,
            num_layers=profile.num_layers,
            num_heads=profile.num_heads,
            page_size=cfg.page_size,
            head_dim=profile.head_dim,
            dtype_bytes=dtype_bytes,
        )

    import torch
    shape = (num_blocks, profile.num_layers,
             profile.num_heads, cfg.page_size, profile.head_dim)

    print(f"[alloc] allocating k_pool {shape} ...")
    k_pool = torch.empty(shape, dtype=torch.float16, device=cfg.device)
    print(f"[alloc] allocating v_pool {shape} ...")
    v_pool = torch.empty(shape, dtype=torch.float16, device=cfg.device)

    allocated_gb = (k_pool.nbytes + v_pool.nbytes) / 1024**3
    print(f"[alloc] allocated            : {allocated_gb:.2f} GB\n")

    return BlockPool(
        k_pool=k_pool, v_pool=v_pool,
        num_blocks=num_blocks,
        num_layers=profile.num_layers,
        num_heads=profile.num_heads,
        page_size=cfg.page_size,
        head_dim=profile.head_dim,
        dtype_bytes=dtype_bytes,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sequence block state
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SequenceBlockState:
    seq_id:          int
    physical_blocks: list[int] = field(default_factory=list)
    num_tokens:      int       = 0


# ─────────────────────────────────────────────────────────────────────────────
# Block space manager — pure-Python free-list over the block pool
# ─────────────────────────────────────────────────────────────────────────────

class BlockSpaceManager:
    """Pure-Python free-list manager over the pre-allocated block pool.

    Tracks which physical blocks are free or in use, assigns blocks to
    sequences on demand, and returns them to the free list when sequences
    finish.

    The Triton/PyTorch kernels never interact with this class directly.
    Before each forward pass, the scheduler calls build_block_table() to
    materialise the current assignments into a GPU tensor.
    """

    def __init__(self, pool: BlockPool) -> None:
        self._pool: BlockPool                       = pool
        self._free: list[int]                       = list(range(pool.num_blocks))
        self._seqs: dict[int, SequenceBlockState]   = {}

    @property
    def num_free_blocks(self) -> int:
        return len(self._free)

    @property
    def num_used_blocks(self) -> int:
        return self._pool.num_blocks - len(self._free)

    def blocks_needed(self, num_tokens: int) -> int:
        return math.ceil(num_tokens / self._pool.page_size)

    def can_allocate(self, num_tokens: int) -> bool:
        return self.blocks_needed(num_tokens) <= len(self._free)

    def allocate(self, seq_id: int, num_tokens: int) -> list[int]:
        n = self.blocks_needed(num_tokens)
        if n > len(self._free):
            raise RuntimeError(
                f"OOM: need {n} blocks for seq {seq_id} "
                f"but only {len(self._free)} free"
            )
        blocks = [self._free.pop() for _ in range(n)]
        self._seqs[seq_id] = SequenceBlockState(
            seq_id=seq_id, physical_blocks=blocks, num_tokens=num_tokens,
        )
        return blocks

    def append_token(self, seq_id: int) -> Optional[int]:
        """Increment token count; allocate a new block if the current page is full."""
        state = self._seqs[seq_id]
        state.num_tokens += 1
        if state.num_tokens % self._pool.page_size != 1:
            return None
        if not self._free:
            raise RuntimeError(f"OOM: no free blocks when extending seq {seq_id}")
        new_block = self._free.pop()
        state.physical_blocks.append(new_block)
        return new_block

    def free(self, seq_id: int) -> None:
        state = self._seqs.pop(seq_id, None)
        if state is not None:
            self._free.extend(state.physical_blocks)

    def rollback(self, seq_id: int, keep_tokens: int) -> None:
        """Shrink a running sequence back to keep_tokens, releasing excess blocks.

        Used by speculative decoding to discard rejected draft tokens from the
        KV cache.  Blocks that are no longer needed are returned to the free
        list so they can be reused immediately.

        keep_tokens must be <= state.num_tokens; calling with keep_tokens equal
        to the current length is a no-op.
        """
        state = self._seqs.get(seq_id)
        if state is None:
            return
        needed = self.blocks_needed(keep_tokens)
        while len(state.physical_blocks) > needed:
            self._free.append(state.physical_blocks.pop())
        state.num_tokens = keep_tokens

    def build_block_table(
        self,
        seq_ids: list[int],
        device:  str = "cuda",
    ) -> tuple:
        """Build block_table and context_lens tensors for the kernel.

        Returns
        -------
        block_table  : [len(seq_ids), max_pages]  int32
        context_lens : [len(seq_ids)]             int32
        """
        import torch

        max_pages    = max(len(self._seqs[sid].physical_blocks) for sid in seq_ids)
        B            = len(seq_ids)
        block_table  = torch.zeros(B, max_pages, dtype=torch.int32, device=device)
        context_lens = torch.zeros(B,            dtype=torch.int32, device=device)

        for i, sid in enumerate(seq_ids):
            state = self._seqs[sid]
            for j, phys in enumerate(state.physical_blocks):
                block_table[i, j] = phys
            context_lens[i] = state.num_tokens

        return block_table, context_lens

    def stats(self) -> dict:
        return {
            "total_blocks": self._pool.num_blocks,
            "free_blocks":  self.num_free_blocks,
            "used_blocks":  self.num_used_blocks,
            "active_seqs":  len(self._seqs),
            "utilization":  f"{self.num_used_blocks / self._pool.num_blocks * 100:.1f}%",
        }
