from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .metrics import centroid, route_features
from .store import RouteSample
from .types import RouteKind


@dataclass(frozen=True)
class SVMModel:
    weights: list[float]
    bias: float
    work_centroid: list[float]
    speak_centroid: list[float]
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": "svm",
            "feature_dim": 2,
            "weights": list(self.weights),
            "bias": float(self.bias),
            "work_centroid": list(self.work_centroid),
            "speak_centroid": list(self.speak_centroid),
            "sample_count": int(self.sample_count),
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> SVMModel:
        return cls(
            weights=[float(v) for v in row.get("weights", [])],
            bias=float(row.get("bias", 0.0)),
            work_centroid=[float(v) for v in row.get("work_centroid", [])],
            speak_centroid=[float(v) for v in row.get("speak_centroid", [])],
            sample_count=int(row.get("sample_count", 0)),
        )

    def score(self, vector: list[float]) -> tuple[float, list[float]]:
        features = route_features(
            vector,
            work_centroid=self.work_centroid,
            speak_centroid=self.speak_centroid,
        )
        score = sum(w * x for w, x in zip(self.weights, features)) + self.bias
        return float(score), features

    def predict(self, vector: list[float]) -> tuple[RouteKind, float, float, list[float]]:
        score, features = self.score(vector)
        confidence = 1.0 / (1.0 + math.exp(-abs(score)))
        route = RouteKind.work if score >= 0.0 else RouteKind.speak
        return route, confidence, score, features


def centroids_for(samples: list[RouteSample]) -> tuple[list[float], list[float]]:
    work = [s.embedding for s in samples if s.label == RouteKind.work]
    speak = [s.embedding for s in samples if s.label == RouteKind.speak]
    if not work or not speak:
        raise ValueError("SVM training requires both work and speak samples")
    return centroid(work), centroid(speak)


def train_linear_svm(
    samples: list[RouteSample],
    *,
    epochs: int = 120,
    lambda_: float = 0.01,
) -> SVMModel:
    work_centroid, speak_centroid = centroids_for(samples)
    rows: list[list[float]] = []
    labels: list[float] = []
    for sample in samples:
        rows.append(route_features(
            sample.embedding,
            work_centroid=work_centroid,
            speak_centroid=speak_centroid,
        ))
        labels.append(1.0 if sample.label == RouteKind.work else -1.0)

    x = np.asarray(rows, dtype=float)
    y = np.asarray(labels, dtype=float)
    weights = np.zeros(x.shape[1], dtype=float)
    bias = 0.0
    step = 0
    for _epoch in range(max(1, int(epochs))):
        for idx in range(x.shape[0]):
            step += 1
            eta = 1.0 / (lambda_ * step)
            margin = y[idx] * (float(np.dot(weights, x[idx])) + bias)
            weights *= 1.0 - eta * lambda_
            if margin < 1.0:
                weights += eta * y[idx] * x[idx]
                bias += eta * y[idx]
    return SVMModel(
        weights=[float(v) for v in weights.tolist()],
        bias=float(bias),
        work_centroid=work_centroid,
        speak_centroid=speak_centroid,
        sample_count=len(samples),
    )
