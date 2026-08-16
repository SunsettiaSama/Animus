from __future__ import annotations

_RENDER_BASE_MS = 320
_RENDER_PER_CHAR_MS = 28
_RENDER_MIN_MS = 450
_RENDER_MAX_MS = 2_400


def estimate_render_time_ms(text: str) -> int:
    """Return the server-authoritative loading duration for one complete speak."""
    length = len("".join(str(text or "").split()))
    return max(
        _RENDER_MIN_MS,
        min(_RENDER_MAX_MS, _RENDER_BASE_MS + length * _RENDER_PER_CHAR_MS),
    )
