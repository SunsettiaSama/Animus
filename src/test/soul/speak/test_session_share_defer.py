from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

share_desire_mod = types.ModuleType("agent.soul.presence.share_desire")
sys.modules["agent.soul.presence.share_desire"] = share_desire_mod


class ShareDesire(str):
    none = "none"
    mild = "mild"
    moderate = "moderate"
    eager = "eager"


share_desire_mod.ShareDesire = ShareDesire

queue_mod = types.ModuleType("agent.soul.presence.state.dynamic.expectation.queue")
sys.modules["agent.soul.presence.state.dynamic.expectation.queue"] = queue_mod


class ShareIntent:
    def __init__(self, topic="", share_desire=ShareDesire.mild, source="", salience=0.0):
        self.topic = topic
        self.share_desire = share_desire
        self.source = source
        self.salience = salience


class ShareIntentQueue:
    def __init__(self, items=None):
        self.items = list(items or [])


queue_mod.ShareIntent = ShareIntent
queue_mod.ShareIntentQueue = ShareIntentQueue

_spec = importlib.util.spec_from_file_location(
    "session_share_queue_under_test",
    SRC / "agent/soul/speak/session/queue/share.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SessionShareQueue = _mod.SessionShareQueue


def test_session_share_queue_enqueue_and_pop_by_salience():
    queue = SessionShareQueue()
    intents = [
        ShareIntent(topic="low", salience=0.2),
        ShareIntent(topic="high", salience=0.9),
    ]
    assert queue.enqueue_batch("s1", intents) == 2
    popped = queue.pop_most_wanted("s1")
    assert popped is not None
    assert popped.topic == "high"
    remaining = queue.as_intent_queue("s1")
    assert len(remaining.items) == 1
    assert remaining.items[0].topic == "low"
