from __future__ import annotations

from storyview.fate.dice import roll_d100
from storyview.gm.outline import OutlineTracker
from storyview.types import StatePatch


class _FakeOutlineStore:
    def active_arc(self, world_id: str):
        return {"id": "arc1", "world_id": world_id}

    def next_optional_beat(self, arc_id: str):
        return {"summary": "在图书馆安静阅读"}


class _FakeStores:
    outline = _FakeOutlineStore()


def test_roll_d100_range():
    for seed in range(5):
        dice = roll_d100(seed=seed)
        assert 1 <= dice.value <= 100
        assert dice.tendency


def test_outline_deviation_active_intent():
    tracker = OutlineTracker(_FakeStores())
    dev, note = tracker.check_deviation("w1", "我决定走向吧台点一杯酒")
    assert dev is True
    assert note


def test_outline_no_deviation_when_aligned():
    tracker = OutlineTracker(_FakeStores())
    dev, _ = tracker.check_deviation("w1", "我决定在图书馆安静阅读")
    assert dev is False


def test_state_patch_roundtrip():
    patch = StatePatch(
        move_to_location_id="loc-1",
        entity_deltas={"e1": {"mixing": True}},
        flags={"night": True},
    )
    restored = StatePatch.from_dict(patch.to_dict())
    assert restored.move_to_location_id == "loc-1"
    assert restored.entity_deltas["e1"]["mixing"] is True
