"""
Custom vLLM inference server — OpenAI-compatible REST API.

Entry point (launched by CustomVLLMManager._build_cmd):

    python -m infra.llm.custom.server
        --model  <hf-model-name-or-path>
        --host   0.0.0.0
        --port   8100
        --max-batch-size  8
        --max-new-tokens  512
        --page-size       16
        --gpu-mem-util    0.85

Architecture
------------
  HTTP layer  (asyncio / uvicorn / FastAPI)
      │
      │  submit()  →  Scheduler waiting queue
      ▼
  Inference loop  (dedicated daemon thread)
      │  schedule() → model.forward() → sample() → update()
      │
      │  per-request asyncio.Queue  (bridge via loop.call_soon_threadsafe)
      ▼
  Streaming SSE response  (asyncio generator)

The inference loop is fully synchronous — PyTorch + HuggingFace work best in a
dedicated thread, not inside the asyncio event loop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# ── sys.path: add src/ so infra.* imports resolve ─────────────────────────────
_SRC = Path(__file__).resolve().parents[3]   # src/infra/llm/custom/server.py → src/
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from infra.llm.custom.block_space_manager.block_manager import (
    BlockPool,
    BlockSpaceManager,
    allocate_block_pool,
)
from infra.llm.custom.block_space_manager.profiler import PreallocConfig, profile_run
from infra.llm.custom.worker.scheduler import Scheduler, SeqStatus

logger = logging.getLogger("vllm-clone.server")


# ═════════════════════════════════════════════════════════════════════════════
#  OpenAI-compatible request / response schemas
# ═════════════════════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    role:    str
    content: str


class ChatCompletionRequest(BaseModel):
    model:            str
    messages:         list[ChatMessage]
    max_tokens:       int  = Field(default=256, ge=1, le=4096)
    temperature:      float = Field(default=1.0, ge=0.0, le=2.0)
    top_p:            float = Field(default=1.0, gt=0.0, le=1.0)
    stream:           bool  = False
    stop:             list[str] | str | None = None


class CompletionRequest(BaseModel):
    model:            str
    prompt:           str | list[int]
    max_tokens:       int  = Field(default=256, ge=1, le=4096)
    temperature:      float = Field(default=1.0, ge=0.0, le=2.0)
    top_p:            float = Field(default=1.0, gt=0.0, le=1.0)
    stream:           bool  = False
    stop:             list[str] | str | None = None


# ═════════════════════════════════════════════════════════════════════════════
#  ModelRunner — wraps HuggingFace model for our inference loop
# ═════════════════════════════════════════════════════════════════════════════

class ModelRunner:
    """Thin wrapper around a HuggingFace CausalLM model.

    Provides ``prefill`` and ``decode`` calls that mirror vLLM's separation
    of the two phases.  The BlockSpaceManager / Scheduler handle memory; the
    HuggingFace model handles the actual computation.

    On GPU (CUDA available): runs in float16, passes use_cache=True.
    On CPU / Windows without CUDA: runs in float32 with KV cache disabled.
    """

    def __init__(self, model_name: str, device: torch.device) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info("Loading tokenizer: %s", model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=True
        )
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token_id = self.tokenizer.eos_token_id

        logger.info("Loading model: %s  device=%s", model_name, device)
        dtype = torch.float16 if device.type == "cuda" else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=dtype,
            device_map=str(device),
            trust_remote_code=True,
        )
        self.model.eval()
        self.device    = device
        self._kv_cache: dict[int, tuple] = {}   # seq_id → past_key_values

    @torch.inference_mode()
    def prefill(
        self,
        seq_id:     int,
        token_ids:  list[int],
        temperature: float = 1.0,
        top_p:       float = 1.0,
    ) -> int:
        """Run prefill for a new sequence; cache KV; return first generated token."""
        input_ids = torch.tensor([token_ids], device=self.device)
        out = self.model(input_ids=input_ids, use_cache=True, return_dict=True)
        self._kv_cache[seq_id] = out.past_key_values
        return self._sample(out.logits[:, -1, :], temperature, top_p)

    @torch.inference_mode()
    def decode(
        self,
        seq_id:      int,
        token_id:    int,
        temperature: float = 1.0,
        top_p:       float = 1.0,
    ) -> int:
        """Run one decode step; update KV cache; return next token."""
        past = self._kv_cache.get(seq_id)
        input_ids = torch.tensor([[token_id]], device=self.device)
        out = self.model(
            input_ids         = input_ids,
            past_key_values   = past,
            use_cache         = True,
            return_dict       = True,
        )
        self._kv_cache[seq_id] = out.past_key_values
        return self._sample(out.logits[:, -1, :], temperature, top_p)

    def free(self, seq_id: int) -> None:
        self._kv_cache.pop(seq_id, None)

    @staticmethod
    def _sample(logits: torch.Tensor, temperature: float, top_p: float) -> int:
        """Greedy (temp≈0) or top-p multinomial sampling."""
        if temperature < 1e-5:
            return int(logits.argmax(dim=-1).item())
        logits = logits / temperature
        probs  = torch.softmax(logits, dim=-1)
        if top_p < 1.0:
            sorted_p, sorted_idx = torch.sort(probs, descending=True)
            cum_p    = torch.cumsum(sorted_p, dim=-1)
            remove   = cum_p - sorted_p > top_p
            sorted_p[remove] = 0.0
            probs.scatter_(1, sorted_idx, sorted_p)
            probs /= probs.sum(dim=-1, keepdim=True)
        return int(torch.multinomial(probs, num_samples=1).item())

    def encode(self, text: str) -> list[int]:
        return self.tokenizer.encode(text, add_special_tokens=True)

    def decode_tokens(self, token_ids: list[int]) -> str:
        return self.tokenizer.decode(token_ids, skip_special_tokens=True)


# ═════════════════════════════════════════════════════════════════════════════
#  InferenceEngine — continuous batching loop
# ═════════════════════════════════════════════════════════════════════════════

class _RequestState:
    __slots__ = ("temperature", "top_p", "token_queue", "loop", "generated_ids")

    def __init__(
        self,
        temperature: float,
        top_p:       float,
        loop:        asyncio.AbstractEventLoop,
    ) -> None:
        self.temperature   = temperature
        self.top_p         = top_p
        self.loop          = loop
        self.token_queue:  asyncio.Queue[int | None] = asyncio.Queue()
        self.generated_ids: list[int] = []


class InferenceEngine:
    """Continuous-batching inference engine.

    A background daemon thread runs ``_loop()`` which alternates between:
      - Prefill steps (new requests entering the running batch)
      - Decode steps  (running requests generating the next token)

    HTTP handlers enqueue requests via ``submit()`` and receive a per-request
    ``asyncio.Queue`` they can ``await`` for streaming tokens.
    """

    def __init__(
        self,
        runner:          ModelRunner,
        scheduler:       Scheduler,
        max_new_tokens:  int,
    ) -> None:
        self._runner         = runner
        self._scheduler      = scheduler
        self._max_new_tokens = max_new_tokens

        self._req_states:  dict[int, _RequestState] = {}
        self._state_lock   = threading.Lock()
        self._eos_token_id = runner.tokenizer.eos_token_id or 2

        # Daemon thread: runs the inference loop
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="vllm-clone-infer"
        )
        self._thread.start()
        logger.info("Inference loop started (thread=%s)", self._thread.name)

    def submit(
        self,
        prompt_tokens: list[int],
        temperature:   float,
        top_p:         float,
        loop:          asyncio.AbstractEventLoop,
        stop_token_ids: list[int] | None = None,
    ) -> asyncio.Queue:
        """Submit a new request; return the per-request token queue."""
        state  = _RequestState(temperature, top_p, loop)
        seq_id = self._scheduler.submit(
            prompt_tokens  = prompt_tokens,
            max_new_tokens = self._max_new_tokens,
            stop_token_ids = stop_token_ids or [self._eos_token_id],
        )
        with self._state_lock:
            self._req_states[seq_id] = state
        return state.token_queue

    # ── Inference loop (runs in background thread) ────────────────────────────

    def _loop(self) -> None:
        while True:
            sched_out = self._scheduler.schedule()

            if sched_out.is_empty:
                time.sleep(0.001)
                continue

            new_token_ids: dict[int, int] = {}

            # Prefill newly admitted sequences
            for req in sched_out.prefill_seqs:
                with self._state_lock:
                    state = self._req_states.get(req.seq_id)
                if state is None:
                    continue

                token_id = self._runner.prefill(
                    req.seq_id, req.prompt_tokens,
                    state.temperature, state.top_p,
                )
                new_token_ids[req.seq_id] = token_id

            # Decode running sequences
            for seq_id in sched_out.decode_seq_ids:
                with self._state_lock:
                    state = self._req_states.get(seq_id)
                if state is None:
                    continue

                req  = self._scheduler._seq_map[seq_id]
                last = req.generated_ids[-1] if req.generated_ids else req.prompt_tokens[-1]
                token_id = self._runner.decode(
                    seq_id, last, state.temperature, state.top_p,
                )
                new_token_ids[seq_id] = token_id

            # Update scheduler and deliver tokens
            finished = self._scheduler.update(new_token_ids)

            for seq_id, token_id in new_token_ids.items():
                with self._state_lock:
                    state = self._req_states.get(seq_id)
                if state is None:
                    continue
                state.generated_ids.append(token_id)
                state.loop.call_soon_threadsafe(state.token_queue.put_nowait, token_id)

            for req in finished:
                sid = req.seq_id
                self._runner.free(sid)
                with self._state_lock:
                    state = self._req_states.pop(sid, None)
                if state:
                    state.loop.call_soon_threadsafe(state.token_queue.put_nowait, None)


# ═════════════════════════════════════════════════════════════════════════════
#  FastAPI app factory
# ═════════════════════════════════════════════════════════════════════════════

def build_app(engine: InferenceEngine, runner: ModelRunner, model_name: str) -> FastAPI:
    app = FastAPI(title="vllm-clone", version="0.1.0")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models() -> dict:
        return {
            "object": "list",
            "data": [{"id": model_name, "object": "model"}],
        }

    # ── /v1/chat/completions ──────────────────────────────────────────────────

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest) -> StreamingResponse | JSONResponse:
        prompt = _build_chat_prompt(req.messages, runner.tokenizer)
        tokens = runner.encode(prompt)
        stop_ids = _collect_stop_ids(req.stop, runner.tokenizer)
        loop   = asyncio.get_running_loop()
        q      = engine.submit(tokens, req.temperature, req.top_p, loop, stop_ids)

        if req.stream:
            return StreamingResponse(
                _stream_chat(q, runner, model_name),
                media_type="text/event-stream",
            )
        return await _collect_chat(q, runner, model_name)

    # ── /v1/completions ───────────────────────────────────────────────────────

    @app.post("/v1/completions")
    async def completions(req: CompletionRequest) -> StreamingResponse | JSONResponse:
        if isinstance(req.prompt, list):
            tokens = req.prompt
        else:
            tokens = runner.encode(req.prompt)
        stop_ids = _collect_stop_ids(req.stop, runner.tokenizer)
        loop   = asyncio.get_running_loop()
        q      = engine.submit(tokens, req.temperature, req.top_p, loop, stop_ids)

        if req.stream:
            return StreamingResponse(
                _stream_completion(q, runner, model_name),
                media_type="text/event-stream",
            )
        return await _collect_completion(q, runner, model_name)

    return app


# ═════════════════════════════════════════════════════════════════════════════
#  Streaming / collection helpers
# ═════════════════════════════════════════════════════════════════════════════

def _ts() -> float:
    return time.time()


async def _stream_chat(
    q: asyncio.Queue, runner: ModelRunner, model: str
) -> AsyncIterator[bytes]:
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    while True:
        token = await q.get()
        if token is None:
            yield b"data: [DONE]\n\n"
            break
        text  = runner.tokenizer.decode([token], skip_special_tokens=True)
        chunk = {
            "id": cid, "object": "chat.completion.chunk", "created": int(_ts()),
            "model": model,
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()


async def _collect_chat(
    q: asyncio.Queue, runner: ModelRunner, model: str
) -> JSONResponse:
    ids: list[int] = []
    while True:
        token = await q.get()
        if token is None:
            break
        ids.append(token)
    text = runner.decode_tokens(ids)
    return JSONResponse({
        "id":      f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object":  "chat.completion",
        "created": int(_ts()),
        "model":   model,
        "choices": [{
            "index":         0,
            "message":       {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {"completion_tokens": len(ids)},
    })


async def _stream_completion(
    q: asyncio.Queue, runner: ModelRunner, model: str
) -> AsyncIterator[bytes]:
    cid = f"cmpl-{uuid.uuid4().hex[:12]}"
    while True:
        token = await q.get()
        if token is None:
            yield b"data: [DONE]\n\n"
            break
        text  = runner.tokenizer.decode([token], skip_special_tokens=True)
        chunk = {
            "id": cid, "object": "text_completion.chunk", "created": int(_ts()),
            "model": model,
            "choices": [{"index": 0, "text": text, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()


async def _collect_completion(
    q: asyncio.Queue, runner: ModelRunner, model: str
) -> JSONResponse:
    ids: list[int] = []
    while True:
        token = await q.get()
        if token is None:
            break
        ids.append(token)
    text = runner.decode_tokens(ids)
    return JSONResponse({
        "id":      f"cmpl-{uuid.uuid4().hex[:12]}",
        "object":  "text_completion",
        "created": int(_ts()),
        "model":   model,
        "choices": [{"index": 0, "text": text, "finish_reason": "stop"}],
        "usage":   {"completion_tokens": len(ids)},
    })


# ═════════════════════════════════════════════════════════════════════════════
#  Tokenisation / prompt building helpers
# ═════════════════════════════════════════════════════════════════════════════

def _build_chat_prompt(messages: list[ChatMessage], tokenizer) -> str:
    """Build a flat chat string; use apply_chat_template when available."""
    dicts = [{"role": m.role, "content": m.content} for m in messages]
    if hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(
            dicts, tokenize=False, add_generation_prompt=True
        )
    parts = []
    for m in messages:
        parts.append(f"{m.role.capitalize()}: {m.content}")
    parts.append("Assistant:")
    return "\n".join(parts)


def _collect_stop_ids(stop: list[str] | str | None, tokenizer) -> list[int]:
    ids: list[int] = []
    if tokenizer.eos_token_id is not None:
        ids.append(tokenizer.eos_token_id)
    if stop is None:
        return ids
    words = [stop] if isinstance(stop, str) else stop
    for w in words:
        enc = tokenizer.encode(w, add_special_tokens=False)
        if enc:
            ids.append(enc[0])
    return ids


# ═════════════════════════════════════════════════════════════════════════════
#  CLI entry point
# ═════════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="vllm-clone server",
        description="Custom vLLM-compatible inference server",
    )
    p.add_argument("--model",          required=True,    help="HF model name or local path")
    p.add_argument("--host",           default="0.0.0.0")
    p.add_argument("--port",           type=int, default=8100)
    p.add_argument("--max-batch-size", type=int, default=8,   dest="max_batch_size")
    p.add_argument("--max-new-tokens", type=int, default=512,  dest="max_new_tokens")
    p.add_argument("--page-size",      type=int, default=16,   dest="page_size")
    p.add_argument("--num-blocks",     type=int, default=1024, dest="num_blocks",
                   help="Number of KV pages in the block pool (ignored when gpu-mem-util is set)")
    p.add_argument("--gpu-mem-util",   type=float, default=None, dest="gpu_mem_util",
                   help="Fraction of GPU memory to allocate for KV cache (e.g. 0.85)")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    args = _parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Using device: %s", device)

    # ── Model ──────────────────────────────────────────────────────────────────
    runner = ModelRunner(args.model, device)

    # ── KV block pool ──────────────────────────────────────────────────────────
    # BlockSpaceManager is used for request-lifecycle metadata (capacity checks,
    # page accounting).  The actual KV tensors are held by the HuggingFace model
    # via past_key_values — the pool tensors (k_pool/v_pool) are therefore None
    # in the CPU / HF-cache path.  Swapping to pure custom kernels later only
    # requires wiring PagedAttentionLayer; the scheduling layer stays unchanged.
    hf_cfg    = runner.model.config
    num_layers = hf_cfg.num_hidden_layers
    num_heads  = getattr(hf_cfg, "num_key_value_heads",
                         getattr(hf_cfg, "num_attention_heads", 8))
    head_dim   = getattr(hf_cfg, "head_dim",
                         hf_cfg.hidden_size // hf_cfg.num_attention_heads)

    num_blocks = args.num_blocks

    if args.gpu_mem_util and device.type == "cuda":
        prof_cfg = PreallocConfig(
            model_name             = args.model,
            page_size              = args.page_size,
            gpu_memory_utilization = args.gpu_mem_util,
            device                 = str(device),
        )
        profile    = profile_run(prof_cfg)
        pool       = allocate_block_pool(profile, prof_cfg)
        num_blocks = pool.num_blocks
        logger.info("Profiled KV pool: %d blocks × page_size=%d", num_blocks, args.page_size)
    else:
        # CPU path or fixed block count: metadata-only pool (k/v tensors = None).
        pool = BlockPool(
            k_pool       = None,
            v_pool       = None,
            num_blocks   = num_blocks,
            num_layers   = num_layers,
            num_heads    = num_heads,
            page_size    = args.page_size,
            head_dim     = head_dim,
            dtype_bytes  = 2,
        )

    block_mgr = BlockSpaceManager(pool)
    scheduler = Scheduler(block_mgr, max_batch_size=args.max_batch_size)
    engine    = InferenceEngine(runner, scheduler, args.max_new_tokens)
    app       = build_app(engine, runner, args.model)

    logger.info("Starting server on %s:%d  model=%s", args.host, args.port, args.model)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
