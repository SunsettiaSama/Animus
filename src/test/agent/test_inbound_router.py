from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from agent.inbound import (
    InboundRouteStore,
    InboundRouter,
    InboundRouterConfig,
    RouteContext,
    RouteKind,
)
from agent.inbound.metrics import route_features


class FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        if "boom" in text:
            raise RuntimeError("embedding unavailable")
        if any(token in text for token in ("实现", "修复", "运行", "任务", "改")):
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if "请求：你帮我实现" in prompt or "请求：请修复" in prompt:
            return "work"
        return "speak"


def _router(tmp_path, *, warmup: int = 1000, min_samples: int = 1000):
    llm = FakeLLM()
    router = InboundRouter(
        store=InboundRouteStore(str(tmp_path / "inbound")),
        embedder=FakeEmbedder(),
        llm=llm,
        config=InboundRouterConfig(
            llm_warmup_requests=warmup,
            svm_min_samples=min_samples,
        ),
    )
    return router, llm


def _ctx(session_id: str) -> RouteContext:
    return RouteContext(session_id=session_id, channel_id=f"c-{session_id}", gen_id=f"g-{session_id}")


def test_route_features_are_two_signed_differences():
    features = route_features(
        [1.0, 0.0, 0.0],
        work_centroid=[1.0, 0.0, 0.0],
        speak_centroid=[0.0, 1.0, 0.0],
    )
    assert len(features) == 2
    assert features[0] > 0.0
    assert features[1] > 0.0

    speak_features = route_features(
        [0.0, 1.0, 0.0],
        work_centroid=[1.0, 0.0, 0.0],
        speak_centroid=[0.0, 1.0, 0.0],
    )
    assert speak_features[0] < 0.0
    assert speak_features[1] < 0.0


def test_first_turn_routes_and_later_turn_is_sticky(tmp_path):
    router, llm = _router(tmp_path)
    decision = router.handle("你帮我实现这个模块", _ctx("s1"))
    assert decision.route == RouteKind.work
    assert decision.source == "llm"
    assert len(decision.features) == 2

    sticky = router.handle("你好，我们继续聊", _ctx("s1"))
    assert sticky.route == RouteKind.work
    assert sticky.meta["sticky"] is True
    assert llm.calls == 1


def test_svm_takes_over_after_warmup_and_training(tmp_path):
    router, llm = _router(tmp_path, warmup=1, min_samples=2)
    first = router.handle("你帮我实现这个模块", _ctx("s1"))
    assert first.source == "llm"
    router.train_now()

    second = router.handle("请修复测试", _ctx("s2"))
    assert second.source == "svm"
    assert second.route == RouteKind.work
    assert len(second.features) == 2
    assert llm.calls == 1


def test_pierce_updates_gold_label(tmp_path):
    router, _llm = _router(tmp_path)
    decision = router.handle("你好，陪我聊聊", _ctx("s1"))
    assert decision.route == RouteKind.speak

    result = router.pierce("s1", RouteKind.work)
    assert result.previous_route == RouteKind.speak
    assert result.true_route == RouteKind.work

    sticky = router.handle("后续不会重新分类", _ctx("s1"))
    assert sticky.route == RouteKind.work


def test_embedding_failure_stops_before_llm(tmp_path):
    router, llm = _router(tmp_path)
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        router.handle("boom", _ctx("s1"))
    assert llm.calls == 0
