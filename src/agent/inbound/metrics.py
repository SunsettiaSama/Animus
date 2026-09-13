from __future__ import annotations

import math


def dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def l2_norm(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values))


def cosine(left: list[float], right: list[float]) -> float:
    ln = l2_norm(left)
    rn = l2_norm(right)
    if ln == 0.0 or rn == 0.0:
        return 0.0
    return dot(left, right) / (ln * rn)


def l2_distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) * (a - b) for a, b in zip(left, right)))


def centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    width = len(vectors[0])
    sums = [0.0] * width
    for vector in vectors:
        for idx, value in enumerate(vector[:width]):
            sums[idx] += float(value)
    return [value / len(vectors) for value in sums]


def route_features(
    vector: list[float],
    *,
    work_centroid: list[float],
    speak_centroid: list[float],
) -> list[float]:
    if not vector or not work_centroid or not speak_centroid:
        raise ValueError("route features require vector and both centroids")
    cos_work = cosine(vector, work_centroid)
    cos_speak = cosine(vector, speak_centroid)
    l2_work = l2_distance(vector, work_centroid)
    l2_speak = l2_distance(vector, speak_centroid)
    return [
        cos_work - cos_speak,
        l2_speak - l2_work,
    ]
