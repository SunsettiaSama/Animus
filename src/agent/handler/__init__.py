"""Agent 级 handler 包 — 按场景分子包（如 continuity）。"""

from .continuity import (
    CallableContinuityEmbedHandler,
    ContinuityEmbedHandler,
    ContinuityLlmHandler,
    InfraContinuityLlmHandler,
    cosine_similarity,
    parse_continuity_verdict_line,
)

__all__ = [
    "CallableContinuityEmbedHandler",
    "ContinuityEmbedHandler",
    "ContinuityLlmHandler",
    "InfraContinuityLlmHandler",
    "cosine_similarity",
    "parse_continuity_verdict_line",
]
