from __future__ import annotations

import threading
from dataclasses import dataclass

from infra.embedding.service import EmbeddingService

from .classifier import SVMModel, centroids_for, train_linear_svm
from .llm_judge import EmbeddingGroundedLLMJudge
from .store import InboundRouteStore, SEED_SAMPLES
from .types import PierceResult, RouteContext, RouteDecision, RouteKind


@dataclass(frozen=True)
class InboundRouterConfig:
    llm_warmup_requests: int = 1000
    svm_min_samples: int = 1000


class InboundRouter:
    def __init__(
        self,
        *,
        store: InboundRouteStore,
        embedder: EmbeddingService,
        llm,
        config: InboundRouterConfig | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._llm_judge = EmbeddingGroundedLLMJudge(llm)
        self._config = config or InboundRouterConfig()
        weights = store.weights()
        self._model = (
            SVMModel.from_dict(weights)
            if weights and int(weights.get("feature_dim", 0)) == 2
            else None
        )
        self._train_lock = threading.Lock()
        self._training = False

    def handle(self, text: str, ctx: RouteContext) -> RouteDecision:
        existing = self._store.session_route(ctx.session_id)
        if existing is not None:
            return RouteDecision(
                route=RouteKind(str(existing.get("route", RouteKind.speak.value))),
                session_id=ctx.session_id,
                question=str(existing.get("question", text)),
                sample_id=str(existing.get("sample_id", "")),
                source=str(existing.get("source", "sticky")),
                meta={"sticky": True},
            )

        clean = text.strip()
        if not clean:
            raise ValueError("inbound route requires non-empty text")
        self._ensure_seed_samples()
        vector = self._embedder.embed_query(clean)
        request_count = self._store.increment_first_request_count()

        if self._should_use_svm(request_count):
            decision = self._decide_with_svm(clean, vector, ctx)
        else:
            decision = self._decide_with_llm(clean, vector, ctx, request_count=request_count)
        self._store.set_session_route(
            ctx.session_id,
            route=decision.route,
            question=clean,
            sample_id=decision.sample_id,
            source=decision.source,
        )
        self._maybe_train_async()
        return decision

    def pierce(self, session_id: str, true_route: RouteKind | str) -> PierceResult:
        true_kind = true_route if isinstance(true_route, RouteKind) else RouteKind(str(true_route))
        existing = self._store.session_route(session_id)
        if existing is None:
            raise KeyError(f"session has no route decision: {session_id}")
        previous = RouteKind(str(existing.get("route", RouteKind.speak.value)))
        sample_id = str(existing.get("sample_id", ""))
        question = str(existing.get("question", ""))
        self._store.update_sample_label(
            sample_id,
            true_label=true_kind,
            predicted=previous,
        )
        self._store.record_pierce(
            session_id=session_id,
            sample_id=sample_id,
            previous=previous,
            true_label=true_kind,
            text=question,
        )
        self._store.set_session_route(
            session_id,
            route=true_kind,
            question=question,
            sample_id=sample_id,
            source="pierce",
        )
        self._maybe_train_async()
        return PierceResult(
            ok=True,
            session_id=session_id,
            true_route=true_kind,
            previous_route=previous,
            question=question,
            sample_id=sample_id,
        )

    def train_now(self) -> None:
        self._train_and_publish()

    def _decide_with_llm(
        self,
        text: str,
        vector: list[float],
        ctx: RouteContext,
        *,
        request_count: int,
    ) -> RouteDecision:
        samples = self._store.samples()
        work_centroid, speak_centroid = centroids_for(samples)
        judgement = self._llm_judge.judge(
            text,
            vector=vector,
            samples=samples,
            work_centroid=work_centroid,
            speak_centroid=speak_centroid,
        )
        sample = self._store.add_sample(
            text=text,
            label=judgement.route,
            embedding=vector,
            source="llm",
            session_id=ctx.session_id,
        )
        return RouteDecision(
            route=judgement.route,
            session_id=ctx.session_id,
            question=text,
            sample_id=sample.id,
            source="llm",
            confidence=judgement.confidence,
            features=list(judgement.features),
            meta={"request_count": request_count, "raw": judgement.raw},
        )

    def _decide_with_svm(
        self,
        text: str,
        vector: list[float],
        ctx: RouteContext,
    ) -> RouteDecision:
        if self._model is None:
            raise RuntimeError("SVM route model is not ready")
        route, confidence, score, features = self._model.predict(vector)
        sample = self._store.add_sample(
            text=text,
            label=route,
            embedding=vector,
            source="svm",
            session_id=ctx.session_id,
        )
        return RouteDecision(
            route=route,
            session_id=ctx.session_id,
            question=text,
            sample_id=sample.id,
            source="svm",
            confidence=confidence,
            score=score,
            features=features,
            meta={"sample_count": self._model.sample_count},
        )

    def _should_use_svm(self, request_count: int) -> bool:
        return (
            self._model is not None
            and request_count > self._config.llm_warmup_requests
            and self._store.gold_count() >= self._config.svm_min_samples
        )

    def _maybe_train_async(self) -> None:
        if self._store.gold_count() < self._config.svm_min_samples:
            return
        with self._train_lock:
            if self._training:
                return
            self._training = True
        thread = threading.Thread(
            target=self._train_and_publish,
            name="inbound-route-svm-train",
            daemon=True,
        )
        thread.start()

    def _train_and_publish(self) -> None:
        samples = self._store.samples()
        model = train_linear_svm(samples)
        self._store.save_weights(model.to_dict())
        self._model = model
        with self._train_lock:
            self._training = False

    def _ensure_seed_samples(self) -> None:
        existing = self._store.samples()
        if any(sample.source == "seed" for sample in existing):
            return
        for text, label in SEED_SAMPLES:
            vector = self._embedder.embed_query(text)
            self._store.add_sample(
                text=text,
                label=label,
                embedding=vector,
                source="seed",
            )
