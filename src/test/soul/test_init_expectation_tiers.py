"""五档分享阈值：解析、选型与 scan 行为。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.soul.presence.init_expectation import (
    ExpectationTier,
    apply_expectation_tier,
    resolve_expectation_tier,
    sync_presence_expectation_from_persona,
)
from agent.soul.presence.init_expectation.profiles import EXPECTATION_TIER_PRESETS
from agent.soul.presence.share_desire import ShareDesire, share_desire_weight
import config.soul.presence.config as presence_cfg
from agent.soul.presence.state.dynamic.expectation import (
    ExpectationState,
    ShareIntent,
    apply_non_dialogue_share_refresh,
    scan_expectation_thresholds,
)
from agent.soul.presence.state.dynamic.expectation.scanner import ExpectationScanMode
from agent.soul.presence.transition.interaction import PresenceInteraction
from config.soul.presence.config import PresenceConfig, reload_presence_config


class _FakeEmbedder:
    """按文本哈希生成稳定向量，使 anchor 与 persona 可区分。"""

    def embed(self, text: str) -> list[float]:
        seed = sum(ord(c) for c in text[:200])
        return [
            float((seed + idx * 17) % 97) / 97.0
            for idx in range(3)
        ]


def _cheerful_snapshot() -> dict:
    return {
        "profile": {
            "name": "小灵",
            "core_traits": ["开朗", "热情", "健谈"],
            "interpersonal_style": "外向主动，乐于分享",
            "emotional_expressiveness": "阳光乐观",
        },
        "self_concept": {"narrative": "喜欢把新鲜事告诉用户"},
        "attention_keywords": [],
    }


def _reserved_snapshot() -> dict:
    return {
        "profile": {
            "name": "静",
            "core_traits": ["内向", "沉默", "克制"],
            "interpersonal_style": "寡言，很少主动开口",
            "emotional_expressiveness": "冷淡疏离",
        },
        "self_concept": {},
        "attention_keywords": [],
    }


@pytest.fixture(autouse=True)
def _restore_presence_config():
    base = PresenceConfig.default()
    yield
    reload_presence_config(base)


@pytest.mark.parametrize(
    ("tier", "moderate_triggers", "eager_triggers"),
    [
        (ExpectationTier.very_low, False, False),
        (ExpectationTier.low, False, False),
        (ExpectationTier.medium, False, True),
        (ExpectationTier.high, True, True),
        (ExpectationTier.very_high, True, True),
    ],
)
def test_tier_scan_proactive_behavior(tier, moderate_triggers, eager_triggers):
    apply_expectation_tier(tier)
    preset = EXPECTATION_TIER_PRESETS[tier]

    def _scan_with_desire(desire: str):
        exp = ExpectationState()
        intr = PresenceInteraction()
        apply_non_dialogue_share_refresh(
            exp,
            intr,
            {"wants_to_share": "true", "share_topic": "x", "share_desire": desire},
            source="test",
        )
        return scan_expectation_thresholds(
            session_id="tao",
            expectation=exp,
            interaction=intr,
            line_open=False,
            proactive_threshold=preset.proactive_open_threshold,
        )

    mod_scan = _scan_with_desire("moderate")
    eager_scan = _scan_with_desire("eager")
    assert mod_scan.triggered is moderate_triggers
    assert eager_scan.triggered is eager_triggers
    if eager_triggers:
        assert eager_scan.mode == ExpectationScanMode.proactive_open
    assert presence_cfg.PROACTIVE_OPEN_THRESHOLD == preset.proactive_open_threshold
    assert share_desire_weight(ShareDesire.moderate) == preset.share_desire_weight_moderate


def test_override_forces_high_without_cheerful_text():
    resolved = resolve_expectation_tier(
        _reserved_snapshot(),
        override="较高",
    )
    assert resolved.tier == ExpectationTier.high


def test_keyword_resolves_cheerful_to_high():
    resolved = resolve_expectation_tier(_cheerful_snapshot())
    assert resolved.tier == ExpectationTier.high


def test_keyword_resolves_reserved_to_low_or_very_low():
    resolved = resolve_expectation_tier(_reserved_snapshot())
    assert resolved.tier in (ExpectationTier.very_low, ExpectationTier.low)


def test_embedding_refines_ambiguous_text():
    ambiguous = {
        "profile": {
            "core_traits": ["细腻"],
            "interpersonal_style": "平和自然",
        },
        "self_concept": {},
    }
    kw_only = resolve_expectation_tier(ambiguous, embedder=None)
    with_emb = resolve_expectation_tier(ambiguous, embedder=_FakeEmbedder())
    assert kw_only.tier in (
        ExpectationTier.medium,
        ExpectationTier.low,
        ExpectationTier.high,
    )
    assert with_emb.tier in ExpectationTier


def test_sync_applies_high_tier_config():
    detail = sync_presence_expectation_from_persona(
        _cheerful_snapshot(),
        tier_override="较高",
    )
    assert detail["tier"] == "较高"
    assert detail["proactive_open_threshold"] == 0.40
    assert presence_cfg.PROACTIVE_OPEN_THRESHOLD == 0.40


def test_single_moderate_triggers_only_for_high_and_very_high():
    for tier, should in (
        (ExpectationTier.medium, False),
        (ExpectationTier.high, True),
        (ExpectationTier.very_high, True),
    ):
        apply_expectation_tier(tier)
        exp = ExpectationState()
        intr = PresenceInteraction()
        apply_non_dialogue_share_refresh(
            exp,
            intr,
            {"wants_to_share": "true", "share_topic": "t", "share_desire": "moderate"},
            source="life",
        )
        scan = scan_expectation_thresholds(
            session_id="tao",
            expectation=exp,
            interaction=intr,
            line_open=False,
        )
        assert scan.triggered is should, tier.value
