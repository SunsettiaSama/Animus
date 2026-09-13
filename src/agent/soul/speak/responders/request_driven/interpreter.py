from __future__ import annotations

import re
from dataclasses import dataclass

from .protocol.blocks import parse_role_blocks, strip_role_tag_debris
from .timeline import RoleTimeline, TimelineOp

_WAIT_RE = re.compile(r"^\s*wait(?:\s+(\d+(?:\.\d+)?)\s*s?)?\s*$", re.IGNORECASE)
_SILENCE_RE = re.compile(r"^\s*silence(?:\s+(\d+(?:\.\d+)?)\s*s?)?\s*$", re.IGNORECASE)
_EMIT_RE = re.compile(r"^\s*emit\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class RoleInterpretResult:
    timeline: RoleTimeline
    help_goals: tuple[str, ...] = ()
    notes_to_director: tuple[str, ...] = ()
    notes_to_screenwriter: tuple[str, ...] = ()


def interpret_role_output(raw: str) -> RoleTimeline:
    return interpret_role_packet(raw).timeline


def _split_speak_messages(text: str) -> tuple[str, ...]:
    """speak 块内按空行拆消息；无空行则整块算一条。"""
    body = str(text or "").strip()
    if not body:
        return ()
    pieces = tuple(p.strip() for p in re.split(r"\n\s*\n", body) if p.strip())
    return pieces or (body,)


def interpret_role_packet(raw: str) -> RoleInterpretResult:
    """按标签出现顺序解析；order 由解析侧递增编号，不依赖模型写 i=。"""
    blocks = parse_role_blocks(raw)
    ops: list[TimelineOp] = []
    ignored: list[str] = []
    bind: list[str] = []
    help_goals: list[str] = []
    notes_director: list[str] = []
    notes_screenwriter: list[str] = []
    order = 0

    def _next_meta() -> dict[str, object]:
        nonlocal order
        meta = {"order": order}
        order += 1
        return meta

    for block in blocks:
        if block.kind == "speak":
            text = strip_role_tag_debris(block.content)
            # 一块 speak 里的多条消息（空行分隔）拆成多个 emit：
            # 每条独立投递、独立入账本，前端才是一个气泡一句话。
            for piece in _split_speak_messages(text):
                ops.append(TimelineOp(kind="emit", texts=(piece,), meta=_next_meta()))
            continue
        if block.kind == "think":
            thought = block.content.strip()
            if thought:
                ops.append(TimelineOp(kind="think", body=thought, meta=_next_meta()))
            continue
        if block.kind == "ask_help":
            goal = block.content.strip()
            if goal:
                help_goals.append(goal)
            continue
        if block.kind == "note_director":
            note = block.content.strip()
            if note:
                notes_director.append(note)
            continue
        if block.kind == "note_screenwriter":
            note = block.content.strip()
            if note:
                notes_screenwriter.append(note)
            continue
        if block.kind == "speak_context":
            text = block.content.strip()
            if text:
                bind.append(text)
            continue
        if block.kind == "body_action":
            continue
        if block.kind != "speak_action":
            ignored.append(f"unknown:{block.raw_tag}:{block.content[:40]}")
            continue
        action_op = _parse_speak_action(block.content, bind=bind, meta=_next_meta())
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
                meta={"auto_flush": True, "order": order},
            )
        )

    return RoleInterpretResult(
        timeline=RoleTimeline(ops=tuple(ops), ignored=tuple(ignored)),
        help_goals=tuple(help_goals),
        notes_to_director=tuple(notes_director),
        notes_to_screenwriter=tuple(notes_screenwriter),
    )


def _parse_speak_action(
    content: str,
    *,
    bind: list[str],
    meta: dict[str, object] | None = None,
) -> tuple[TimelineOp, bool] | None:
    text = content.strip()
    if not text:
        return None
    payload = dict(meta or {})
    m_wait = _WAIT_RE.match(text)
    if m_wait is not None:
        seconds = float(m_wait.group(1) or "0")
        return TimelineOp(kind="wait", seconds=max(0.0, seconds), meta=payload), False
    m_silence = _SILENCE_RE.match(text)
    if m_silence is not None:
        seconds = float(m_silence.group(1) or "0")
        return (
            TimelineOp(
                kind="silence",
                seconds=max(0.0, seconds),
                meta={**payload, "silence": True},
            ),
            False,
        )
    if _EMIT_RE.match(text) is not None:
        return TimelineOp(kind="emit", texts=tuple(bind), meta=payload), True
    return None
