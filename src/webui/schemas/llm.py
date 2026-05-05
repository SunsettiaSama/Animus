from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


# ── REST request bodies ───────────────────────────────────────────────────────

class InitLLMRequest(BaseModel):
    backend: str = "openai"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 8192
    temperature: float = 0.7
    streaming: bool = True


class PatchLLMRequest(BaseModel):
    """Hot-swap the LLM handle without rebuilding TaoLoop/ConvLoop."""
    backend: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    streaming: bool | None = None


class ChatRequest(BaseModel):
    prompt: str
    history: list[dict] = []


# ── REST response bodies ──────────────────────────────────────────────────────

class LLMStatusResponse(BaseModel):
    initialized: bool
    react_ready: bool
    is_streaming: bool = False
    model: str | None = None
    backend: str | None = None


class LLMConfigResponse(BaseModel):
    backend: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    streaming: bool | None = None


# ── WS chat messages ──────────────────────────────────────────────────────────

class ChatChunk(BaseModel):
    chunk: str | None = None
    done: bool = False
    error: str | None = None
