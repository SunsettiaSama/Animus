from __future__ import annotations

import re
from dataclasses import dataclass

from .protocol.blocks import parse_role_blocks
from .timeline import RoleTimeline, TimelineOp

_WAIT_RE = re.compile(r"^\s*wait(?:\s+(\d+(?:\.\d+)?)\s*s?)?\s*$", re.IGNORECASE)
_SILENCE_RE = re.compile(r"^\s*silence(?:\s+(\d+(?:\.\d+)?)\s*s?)?\s*$", re.IGNORECASE)
_EMIT_RE = re.compile(r"^\s*emit\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class RoleInterpretResult:
    timeline: RoleTimeline
    help_goals: tuple[str, ...] = ()


def interpret_role_output(raw: str) -> RoleTimeline:
    return interpret_role_packet(raw).timeline


def interpret_role_packet(raw: str) -> RoleInterpretResult:
    blocks = parse_role_blocks(raw)
    ops: list[TimelineOp] = []
    ignored: list[str] = []
    bind: list[str] = []
    help_goals: list[str] = []

    for block in blocks:
        if block.kind == "think":
            thought = block.content.strip()
            if thought:
                ops.append(TimelineOp(kind="think", body=thought))
            continue
        if block.kind == "ask_help":
            goal = block.content.strip()
            if goal:
                help_goals.append(goal)
            continue
        if block.kind == "speak_context":
            if block.content.strip():
                bind.append(block.content.strip())
            continue
        if block.kind == "body_action":
            body = block.content.strip()
            if body:
                ops.append(TimelineOp(kind="body", body=body))
            continue
        if block.kind != "speak_action":
            ignored.append(f"unknown:{block.raw_tag}:{block.content[:40]}")
            continue
        action_op = _parse_speak_action(block.content, bind=bind)
        if action_op is None:
            ignored.append(f"bad_action:{block.content[:40]}")
            continue
        op, clear_bind = action_op
        ops.append(op)
        if clear_bind:
            bind = []

    if bind:
        ops.append(
            TimelineOp(
                kind="emit",
                texts=tuple(bind),
                meta={"auto_flush": True},
            )
        )

    return RoleInterpretResult(
        timeline=RoleTimeline(ops=tuple(ops), ignored=tuple(ignored)),
        help_goals=tuple(help_goals),
    )


def _parse_speak_action(
    content: str,
    *,
    bind: list[str],
) -> tuple[TimelineOp, bool] | None:
    text = content.strip()
    if not text:
        return None
    m_wait = _WAIT_RE.match(text)
    if m_wait is not None:
        seconds = float(m_wait.group(1) or "0")
        return TimelineOp(kind="wait", seconds=max(0.0, seconds)), False
    m_silence = _SILENCE_RE.match(text)
    if m_silence is not None:
        seconds = float(m_silence.group(1) or "0")
        return TimelineOp(kind="silence", seconds=max(0.0, seconds), meta={"silence": True}), False
    if _EMIT_RE.match(text) is not None:
        return TimelineOp(kind="emit", texts=tuple(bind)), True
    return None
