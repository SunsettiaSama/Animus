from __future__ import annotations

import pytest

from agent.soul.speak.pipelines import SpeakPipelineRouter, normalize_speak_pipeline
from agent.soul.speak.session.queue import SessionQueueHub, UserInputItem


def test_normalize_speak_pipeline_defaults_to_legacy_qa():
    assert normalize_speak_pipeline(None) == "legacy_qa"
    assert normalize_speak_pipeline("") == "legacy_qa"


def test_normalize_speak_pipeline_accepts_request_driven():
    assert normalize_speak_pipeline("request_driven") == "request_driven"


def test_normalize_speak_pipeline_rejects_unknown_value():
    with pytest.raises(ValueError, match="unknown speak pipeline"):
        normalize_speak_pipeline("classic")


def test_pipeline_router_dispatches_by_user_input_item_pipeline():
    called: list[str] = []

    class _Runner:
        def __init__(self, name: str) -> None:
            self._name = name

        def run(self, item):
            called.append(self._name)
            return item.pipeline

    router = SpeakPipelineRouter(
        legacy_qa=_Runner("legacy"),
        request_driven=_Runner("request"),
    )

    assert router.run(UserInputItem("s1", "hello", pipeline="legacy_qa")) == "legacy_qa"
    assert router.run(UserInputItem("s1", "hello", pipeline="request_driven")) == "request_driven"
    assert called == ["legacy", "request"]


def test_session_queue_preserves_pipeline_for_pending_user_input():
    hub = SessionQueueHub()
    hub.begin_push("s1", "old question")

    hub.submit_user_input(
        "s1",
        "new question",
        stream=True,
        mode="inbound",
        record=True,
        pipeline="request_driven",
    )

    item = hub.pop_pending_user_input("s1")
    assert item is not None
    assert item.pipeline == "request_driven"
    assert item.user_text == "new question"
