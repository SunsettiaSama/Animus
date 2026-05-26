from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agent.soul.speak.session.registry import SpeakSessionRegistry


def test_session_registry_rotates_after_idle_timeout():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [now, now + timedelta(seconds=3700)]

    def _now():
        return times.pop(0)

    lifecycle = MagicMock()
    lifecycle.close_dialogue_interaction.return_value = {"ok": True}
    lifecycle.start_dialogue_session.return_value = {"ok": True}

    registry = SpeakSessionRegistry(
        idle_sec=3600,
        lifecycle=lifecycle,
        now_fn=_now,
    )
    first = registry.ensure_active("tao")
    second = registry.ensure_active("tao")
    assert first.generation == 1
    assert second.generation == 2
    lifecycle.close_dialogue_interaction.assert_called_once_with("tao")
    lifecycle.start_dialogue_session.assert_called_once_with("tao")
