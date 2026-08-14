from __future__ import annotations

import threading
from collections import deque
from time import monotonic


_STORE: dict[str, deque] = {}
_LOCK = threading.Lock()


class RateLimiter:
    """Module-level singleton sliding-window rate limiter.

    All instances share ``_STORE`` so limits are enforced process-wide.
    """

    @staticmethod
    def check(key: str, rpm: int, rph: int) -> None:
        """Raise RuntimeError if the caller is over-rate.

        ``key``  — unique string identifying the channel (e.g. "notify", "bot")
        ``rpm``  — max calls per minute (0 = unlimited)
        ``rph``  — max calls per hour  (0 = unlimited)
        """
        now = monotonic()
        with _LOCK:
            if key not in _STORE:
                _STORE[key] = deque()
            timestamps = _STORE[key]

            # Purge timestamps older than 1 hour
            while timestamps and timestamps[0] < now - 3600:
                timestamps.popleft()

            count_1h = len(timestamps)
            count_1m = sum(1 for t in timestamps if t >= now - 60)

            if rph > 0 and count_1h >= rph:
                raise RuntimeError(
                    f"Rate limit exceeded for {key!r}: {rph} calls/hour reached."
                )
            if rpm > 0 and count_1m >= rpm:
                raise RuntimeError(
                    f"Rate limit exceeded for {key!r}: {rpm} calls/minute reached."
                )
            timestamps.append(now)
