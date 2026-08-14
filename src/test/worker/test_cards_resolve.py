"""Capability card resolve / materialize."""
from __future__ import annotations

import pytest

from worker.cards import get_card_registry, materialize_capability, resolve_capability


def test_profile_and_package_cards_exist():
    reg = get_card_registry()
    for cid in ("minimal", "executor", "coder", "code", "filesystem", "planner"):
        card = reg.resolve(cid)
        assert card.id == cid
        assert card.tool_package


def test_coder_maps_to_code_package():
    card = resolve_capability("coder")
    assert card.tool_package == "code"
    profile = materialize_capability("coder")
    assert profile.tool_package == "code"
    assert profile.max_steps == 15


def test_unknown_card_raises():
    with pytest.raises(KeyError):
        resolve_capability("no_such_card_xyz")
