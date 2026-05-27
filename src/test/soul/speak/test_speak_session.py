from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agent.soul.speak.session import SpeakTurnChunk
from agent.soul.speak.session.lifecycle import (
    CompositeSemanticBoundary,
    EmbeddingSemanticBoundary,
    SessionBootstrap,
    SessionHolder,
    TopicShiftSemanticBoundary,
)
from agent.soul.speak.session.lifecycle.hold.registry import SpeakSessionRegistry
from agent.soul.speak.session.lifecycle.hold.semantic import cosine_distance


def test_session_registry_rotates_after_idle_timeout():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [now, now + timedelta(seconds=3700), now + timedelta(seconds=3700)]

    def _now():
        return times.pop(0)

    lifecycle = MagicMock()
    lifecycle.close_dialogue_interaction.return_value = {
        "ok": True,
        "ingested": True,
        "experience_id": "exp-1",
        "turn_index": 3,
        "source": "dialogue",
    }
    lifecycle.start_dialogue_session.return_value = {"ok": True}

    registry = SpeakSessionRegistry(idle_sec=3600, lifecycle=lifecycle, now_fn=_now)
    bootstrap = SessionBootstrap(registry=registry, inner_lifecycle=lifecycle)
    SessionHolder(bootstrap)

    first, rotated_first = registry.ensure_active("tao")
    second, rotated_second = registry.ensure_active("tao")
    assert first.generation == 1
    assert second.generation == 2
    assert rotated_first is False
    assert rotated_second is True
    lifecycle.close_dialogue_interaction.assert_called_once_with("tao")
    lifecycle.start_dialogue_session.assert_called_once()


def test_cosine_distance_identical_vectors():
    assert cosine_distance([1.0, 0.0], [1.0, 0.0]) == 0.0


def test_embedding_semantic_boundary_rotates_on_distant_topic():
    class _Embedder:
        def embed(self, text: str) -> list[float]:
            if "天气" in text:
                return [1.0, 0.0]
            if "代码" in text:
                return [0.0, 1.0]
            return [0.5, 0.5]

    boundary = EmbeddingSemanticBoundary(_Embedder(), distance_threshold=0.5)
    first = SpeakTurnChunk(session_id="tao", user_text="今天天气怎么样", agent_text="不错")
    second = SpeakTurnChunk(session_id="tao", user_text="帮我写段 Python 代码", agent_text="好")

    assert boundary.should_rotate("tao", last_turn=first) is False
    assert boundary.should_rotate("tao", last_turn=second) is True
    assert "embedding distance" in boundary.reason()


def test_composite_boundary_keeps_explicit_marker():
    class _Embedder:
        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0]

    boundary = CompositeSemanticBoundary(
        explicit=TopicShiftSemanticBoundary(),
        embedding=EmbeddingSemanticBoundary(_Embedder(), distance_threshold=0.01),
    )
    chunk = SpeakTurnChunk(session_id="tao", user_text="/new 聊聊别的", agent_text="好")
    assert boundary.should_rotate("tao", last_turn=chunk) is True
    assert boundary.reason().startswith("explicit marker")


def test_finalize_session_packages_to_life():
    lifecycle = MagicMock()
    lifecycle.close_dialogue_interaction.return_value = {
        "ok": True,
        "ingested": True,
        "experience_id": "exp-42",
        "turn_index": 2,
        "source": "dialogue",
    }
    lifecycle.start_dialogue_session.return_value = {"ok": True}

    bootstrap = SessionBootstrap(inner_lifecycle=lifecycle)
    holder = SessionHolder(bootstrap)

    ended = holder.finalize_session("tao", reason="manual", note="test close")
    assert ended.ingested is True
    assert ended.experience_id == "exp-42"
    assert ended.turn_index == 2
    assert ended.source == "dialogue"
    assert ended.generation == 2
