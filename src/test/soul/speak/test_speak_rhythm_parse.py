from __future__ import annotations

import pytest

from agent.soul.speak.pipelines.rhythm.directors.parse import (
    normalize_gate,
    normalize_share_tag,
    plan_from_payload,
)


def test_normalize_gate_accepts_known_values():
    assert normalize_gate("listen") == "listen"
    assert normalize_gate("SPEAK") == "speak"
    assert normalize_gate("hold") == "hold"
    assert normalize_gate("brew") == "brew"


def test_normalize_gate_rejects_unknown():
    with pytest.raises(ValueError, match="invalid gate"):
        normalize_gate("mute")


def test_normalize_share_tag_variants():
    assert normalize_share_tag(None) == "none"
    assert normalize_share_tag(False) == "none"
    assert normalize_share_tag("none") == "none"
    assert normalize_share_tag(True) == "share"
    assert normalize_share_tag("share") == "share"
    assert normalize_share_tag("expand") == "expand"
    assert normalize_share_tag("recall") == "expand"


def test_normalize_share_tag_rejects_unknown():
    with pytest.raises(ValueError, match="invalid share tag"):
        normalize_share_tag("push")


def test_plan_from_payload_requires_gate():
    with pytest.raises(ValueError, match="missing gate"):
        plan_from_payload({"arc": "x"})


def test_plan_from_payload_auto_segments_for_speak():
    plan = plan_from_payload(
        {
            "gate": "speak",
            "cue": "接住",
            "reply_guide": "短句",
            "share_tag": "none",
        }
    )
    assert plan.gate == "speak"
    assert plan.should_speak
    assert len(plan.segments) == 1
    assert plan.segments[0].wait_reason == "接住"


def test_plan_from_payload_listen_has_no_speak():
    plan = plan_from_payload(
        {
            "gate": "listen",
            "reply_guide": "别开口",
            "share_tag": "none",
        }
    )
    assert not plan.should_speak
    assert plan.segments == ()
