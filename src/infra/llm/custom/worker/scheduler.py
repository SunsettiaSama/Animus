from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from infra.llm.custom.block_space_manager.block_manager import BlockSpaceManager


# ─────────────────────────────────────────────────────────────────────────────
# Sequence status
# ─────────────────────────────────────────────────────────────────────────────

class SeqStatus(Enum):
    WAITING  = "waiting"
    RUNNING  = "running"
    FINISHED = "finished"
    STOPPED  = "stopped"    # aborted by caller before completion


# ─────────────────────────────────────────────────────────────────────────────
# Sequence request
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SequenceRequest:
    seq_id:          int
    prompt_tokens:   list[int]
    max_new_tokens:  int
    stop_token_ids:  list[int]          = field(default_factory=list)
    generated_ids:   list[int]          = field(default_factory=list)
    status:          SeqStatus          = SeqStatus.WAITING

    @property
    def num_prompt_tokens(self) -> int:
        return len(self.prompt_tokens)

    @property
    def num_generated(self) -> int:
        return len(self.generated_ids)

    @property
    def all_tokens(self) -> list[int]:
        return self.prompt_tokens + self.generated_ids

    @property
    def is_finished(self) -> bool:
        if self.status in (SeqStatus.FINISHED, SeqStatus.STOPPED):
            return True
        if self.num_generated >= self.max_new_tokens:
            return True
        if self.generated_ids and self.generated_ids[-1] in self.stop_token_ids:
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler output — consumed by model.forward() each step
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SchedulerOutput:
    # Requests entering prefill this step (first time they hit the GPU)
    prefill_seqs: list[SequenceRequest]
    # Sequence IDs that are already in the KV cache and need a decode step
    decode_seq_ids: list[int]

    @property
    def is_empty(self) -> bool:
        return not self.prefill_seqs and not self.decode_seq_ids

    @property
    def all_seq_ids(self) -> list[int]:
        prefill_ids = [r.seq_id for r in self.prefill_seqs]
        return prefill_ids + self.decode_seq_ids


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────────────

class Scheduler:
    """Coordinates request queues and block allocation for the vllm-clone engine.

    Responsibilities:
    - Accept incoming requests via submit()
    - Each step: decide which sequences to prefill and which to decode
    - After the model runs: update state with newly generated tokens
    - Release physical KV blocks when sequences finish

    The scheduler is agnostic to model architecture and kernels — it only
    speaks to BlockSpaceManager for memory decisions.
    """

    def __init__(
        self,
        block_mgr:      BlockSpaceManager,
        max_batch_size: int = 8,
    ) -> None:
        self._mgr            = block_mgr
        self._max_batch_size = max_batch_size
        self._waiting:  list[SequenceRequest]           = []
        self._running:  list[SequenceRequest]           = []
        self._seq_map:  dict[int, SequenceRequest]      = {}
        self._next_id:  int                             = 0
        self._lock = threading.Lock()

    # ── Submission ────────────────────────────────────────────────────────────

    def submit(
        self,
        prompt_tokens:   list[int],
        max_new_tokens:  int,
        stop_token_ids:  Optional[list[int]] = None,
    ) -> int:
        """Enqueue a new request. Returns the assigned seq_id."""
        with self._lock:
            seq_id = self._next_id
            self._next_id += 1
            req = SequenceRequest(
                seq_id         = seq_id,
                prompt_tokens  = list(prompt_tokens),
                max_new_tokens = max_new_tokens,
                stop_token_ids = list(stop_token_ids or []),
            )
            self._waiting.append(req)
            self._seq_map[seq_id] = req
            return seq_id

    def abort(self, seq_id: int) -> None:
        """Immediately stop a sequence and return its KV blocks to the pool."""
        with self._lock:
            req = self._seq_map.get(seq_id)
            if req is None or req.status in (SeqStatus.FINISHED, SeqStatus.STOPPED):
                return
            req.status = SeqStatus.STOPPED
            if req in self._waiting:
                self._waiting.remove(req)
            if req in self._running:
                self._running.remove(req)
                self._mgr.free(seq_id)

    # ── Per-step scheduling ───────────────────────────────────────────────────

    def schedule(self) -> SchedulerOutput:
        """Decide what to execute this step.

        Called once per inference step before model.forward().

        Admission policy (simple FCFS):
          Admit waiting requests as long as blocks are available and
          batch size is not exceeded. Requests that cannot be admitted
          stay in the waiting queue for the next step.
        """
        with self._lock:
            prefill_seqs: list[SequenceRequest] = []

            for req in list(self._waiting):
                # Batch size cap: count already-running + already-admitted this step
                if len(self._running) + len(prefill_seqs) >= self._max_batch_size:
                    break

                if not self._mgr.can_allocate(req.num_prompt_tokens):
                    # OOM — skip this request for now; it stays in _waiting
                    continue

                self._mgr.allocate(req.seq_id, req.num_prompt_tokens)
                req.status = SeqStatus.RUNNING
                self._waiting.remove(req)
                self._running.append(req)
                prefill_seqs.append(req)

            # Sequences already running that are NOT being prefilled this step
            prefill_ids   = {r.seq_id for r in prefill_seqs}
            decode_seq_ids = [
                r.seq_id for r in self._running
                if r.seq_id not in prefill_ids
            ]

            return SchedulerOutput(
                prefill_seqs   = prefill_seqs,
                decode_seq_ids = decode_seq_ids,
            )

    # ── Post-step update ──────────────────────────────────────────────────────

    def update(self, new_token_ids: dict[int, int]) -> list[SequenceRequest]:
        """Append new tokens and handle finished sequences.

        Called once per inference step after model.forward() returns logits
        and sampling has been applied.

        Parameters
        ----------
        new_token_ids : {seq_id: token_id}
            One sampled token per running sequence.

        Returns
        -------
        List of sequences that finished this step (for response delivery).
        """
        finished: list[SequenceRequest] = []

        with self._lock:
            for req in list(self._running):
                token_id = new_token_ids.get(req.seq_id)
                if token_id is None:
                    continue

                req.generated_ids.append(token_id)
                # Extend KV cache by one slot; BlockSpaceManager handles
                # cross-page boundary allocation automatically.
                self._mgr.append_token(req.seq_id)

                if req.is_finished:
                    req.status = SeqStatus.FINISHED
                    self._mgr.free(req.seq_id)
                    self._running.remove(req)
                    finished.append(req)

        return finished

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            return {
                "waiting":    len(self._waiting),
                "running":    len(self._running),
                "block_stats": self._mgr.stats(),
            }
