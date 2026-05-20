"""连续性（continuity）专用 handler — 供 interaction.dialogue 注入。"""

from .embedding import CallableContinuityEmbedHandler, cosine_similarity
from .llm import InfraContinuityLlmHandler, parse_continuity_verdict_line
from .protocols import ContinuityEmbedHandler, ContinuityLlmHandler

__all__ = [
    "CallableContinuityEmbedHandler",
    "ContinuityEmbedHandler",
    "ContinuityLlmHandler",
    "InfraContinuityLlmHandler",
    "cosine_similarity",
    "parse_continuity_verdict_line",
]
