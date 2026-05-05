from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# ── Server → Client ───────────────────────────────────────────────────────────

class PromptPreviewMsg(BaseModel):
    type: Literal["prompt_preview"]
    messages: list[dict]


class StepStartMsg(BaseModel):
    type: Literal["step_start"]
    index: int


class ChunkMsg(BaseModel):
    type: Literal["chunk"]
    index: int
    chunk: str


class StepMsg(BaseModel):
    type: Literal["step"]
    index: int
    thought: str
    action: str
    action_input: dict
    observation: str


class RetryMsg(BaseModel):
    type: Literal["retry"]
    index: int
    reason: str


class FinishMsg(BaseModel):
    type: Literal["finish"]
    answer: str
    aborted: bool = False


class ApprovalRequestMsg(BaseModel):
    type: Literal["approval_request"]
    request_id: str
    tool_name: str
    args: dict
    risk_level: str
    reason: str
    deadline_secs: int


class ErrorMsg(BaseModel):
    type: Literal["error"]
    message: str


ReactServerMsg = Annotated[
    Union[
        PromptPreviewMsg,
        StepStartMsg,
        ChunkMsg,
        StepMsg,
        RetryMsg,
        FinishMsg,
        ApprovalRequestMsg,
        ErrorMsg,
    ],
    Field(discriminator="type"),
]


# ── Client → Server ───────────────────────────────────────────────────────────

class AbortMsg(BaseModel):
    type: Literal["abort"]
    gen_id: str


class ApprovalResponseMsg(BaseModel):
    type: Literal["approval_response"]
    request_id: str
    approved: bool


ReactClientMsg = Annotated[
    Union[AbortMsg, ApprovalResponseMsg],
    Field(discriminator="type"),
]
