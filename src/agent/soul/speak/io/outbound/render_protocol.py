"""Speak 前后端渲染协议（字段契约）。

原则：
- 后端负责从 character 字符串解析并拆成字段事件；
- 前端只消费 SpeakStreamEvent 的 kind + 约定 meta 字段渲染；
- 前端禁止解析 character 原始标签字符串。

Character LLM 线格式（仅后端解析，不对前端暴露）：
  <speak context>台词</speak context>
  <speak action>emit|wait N|silence N</speak action>
  <body action>姿态</body action>
  <ask help>自然语言目标</ask help>

可见渲染字段（前端只认这些）：
  thought | speak | body | wait | silence | typing | finish
"""
from __future__ import annotations

from typing import Any, Literal

# 前端可渲染字段（稳定契约；增删需前后端同步）
SpeakRenderField = Literal[
    "thought",
    "speak",
    "body",
    "wait",
    "silence",
    "typing",
    "finish",
]

SPEAK_RENDER_FIELDS: frozenset[str] = frozenset(
    {"thought", "speak", "body", "wait", "silence", "typing", "finish"}
)

# stream event.kind → 默认 field（若 meta.field 缺失时的回填）
_KIND_TO_FIELD: dict[str, str] = {
    "thought": "thought",
    "speak": "speak",
    "segment": "speak",
    "action": "body",
    "agent_typing": "typing",
    "finish": "finish",
}

# field → 前端展示用短标签
FIELD_LABELS: dict[str, str] = {
    "thought": "think",
    "speak": "speak",
    "body": "body",
    "wait": "wait",
    "silence": "silence",
    "typing": "typing",
    "finish": "finish",
}

# 约定 meta 键（前端只读这些）
META_FIELD = "field"
META_LABEL = "label"
META_PHASE = "phase"
META_WAIT_MS = "wait_ms"
META_SECONDS = "seconds"
META_SESSION_STATE = "session_state"


def normalize_render_field(value: str | None) -> str | None:
    key = str(value or "").strip().lower()
    if key in SPEAK_RENDER_FIELDS:
        return key
    return None


def field_for_stream_kind(kind: str, meta: dict[str, Any] | None = None) -> str | None:
    meta = meta or {}
    explicit = normalize_render_field(str(meta.get(META_FIELD) or ""))
    if explicit:
        return explicit
    kind_key = str(kind or "").strip().lower()
    if kind_key == "state":
        # wait/silence 走 state 通道；session_state 不算渲染字段
        role_op = str(meta.get("role_op") or meta.get("wait_reason") or "").strip().lower()
        if role_op in ("wait", "silence"):
            return role_op
        text = str(meta.get("label") or "").strip().lower()
        if text in ("wait", "silence"):
            return text
        return None
    return _KIND_TO_FIELD.get(kind_key)


def render_meta(
    field: SpeakRenderField,
    *,
    phase: str = "",
    wait_ms: int | None = None,
    seconds: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造前端可消费的 meta；只放入协议字段。"""
    meta: dict[str, Any] = {
        META_FIELD: field,
        META_LABEL: FIELD_LABELS.get(field, field),
    }
    if phase:
        meta[META_PHASE] = phase
    if wait_ms is not None:
        meta[META_WAIT_MS] = int(wait_ms)
    if seconds is not None:
        meta[META_SECONDS] = float(seconds)
    if extra:
        for key, value in extra.items():
            if key in (META_FIELD, META_LABEL, META_PHASE, META_WAIT_MS, META_SECONDS):
                continue
            # session_state 仅允许 finish/append/share/recall
            if key == META_SESSION_STATE:
                state = str(value or "").strip().lower()
                if state in ("finish", "append", "share", "recall"):
                    meta[META_SESSION_STATE] = state
                continue
            meta[key] = value
    return meta
