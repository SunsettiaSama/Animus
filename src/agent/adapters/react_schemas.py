from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReactInitRequest(BaseModel):
    lang: str = "cn"
    max_steps: int = 10
    primary_tools: list[str] | None = None
    enable_kb: bool = False


class ReactRunRequest(BaseModel):
    question: str
    stream_mode: Literal["chunk", "flush", "live", "batched"] = Field(
        default="chunk",
        description='chunk/live：分片输出；flush/batched：同一步 token 聚合后一条。',
    )


class RestoreRequest(BaseModel):
    messages: list[dict]
