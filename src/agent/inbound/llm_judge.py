from __future__ import annotations

from dataclasses import dataclass

from .metrics import cosine, l2_distance, route_features
from .store import RouteSample
from .types import RouteKind


@dataclass(frozen=True)
class LLMRouteJudgement:
    route: RouteKind
    raw: str
    features: list[float]
    confidence: float


class EmbeddingGroundedLLMJudge:
    def __init__(self, llm, *, neighbor_count: int = 8) -> None:
        self._llm = llm
        self._neighbor_count = max(1, int(neighbor_count))

    def judge(
        self,
        text: str,
        *,
        vector: list[float],
        samples: list[RouteSample],
        work_centroid: list[float],
        speak_centroid: list[float],
    ) -> LLMRouteJudgement:
        if self._llm is None:
            raise RuntimeError("inbound route LLM is not configured")
        features = route_features(
            vector,
            work_centroid=work_centroid,
            speak_centroid=speak_centroid,
        )
        neighbors = self._nearest(vector, samples)
        prompt = self._prompt(text, features=features, neighbors=neighbors)
        raw = self._llm.generate(prompt).strip()
        route = self._parse(raw)
        confidence = 0.7
        if raw.lower().startswith(route.value):
            confidence = 0.85
        return LLMRouteJudgement(
            route=route,
            raw=raw,
            features=features,
            confidence=confidence,
        )

    def _nearest(
        self,
        vector: list[float],
        samples: list[RouteSample],
    ) -> list[tuple[RouteSample, float, float]]:
        scored = [
            (sample, cosine(vector, sample.embedding), l2_distance(vector, sample.embedding))
            for sample in samples
            if sample.embedding
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:self._neighbor_count]

    @staticmethod
    def _parse(raw: str) -> RouteKind:
        text = raw.strip().lower()
        first = text.splitlines()[0].strip() if text else ""
        if first.startswith("work") or "worker" in first or "任务" in first:
            return RouteKind.work
        if first.startswith("speak") or "chat" in first or "对话" in first:
            return RouteKind.speak
        raise ValueError(f"route LLM must answer speak or work, got: {raw!r}")

    @staticmethod
    def _prompt(
        text: str,
        *,
        features: list[float],
        neighbors: list[tuple[RouteSample, float, float]],
    ) -> str:
        lines = [
            "你是 WebUI 首轮请求路由器，只能输出 speak 或 work。",
            "speak=聊天/表达/解释/陪伴；work=要求 agent 实际执行、修改、运行、检查、查找或生成交付物。",
            "分类依赖 embedding 近邻和二维特征；f1=cos_work-cos_speak，f2=l2_speak-l2_work，越大越偏 work。",
            "不要输出解释。",
            "",
            f"请求：{text.strip()}",
            (
                "特征："
                f"f1_cos_diff={features[0]:.4f}, "
                f"f2_l2_diff={features[1]:.4f}"
            ),
            "近邻：",
        ]
        for sample, sim, dist in neighbors:
            lines.append(
                f"- label={sample.label.value} cos={sim:.4f} l2={dist:.4f} text={sample.text}"
            )
        lines.append("只输出 speak 或 work。")
        return "\n".join(lines)
