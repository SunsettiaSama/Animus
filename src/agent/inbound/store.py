from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from infra.storage.json_store import JsonStorageService

from .types import RouteKind


SEED_SAMPLES: tuple[tuple[str, RouteKind], ...] = (
    ("你帮我实现这个路由", RouteKind.work),
    ("请修复这个测试失败", RouteKind.work),
    ("运行一下单元测试并看失败原因", RouteKind.work),
    ("帮我改一下 webui 的交互", RouteKind.work),
    ("查一下这个模块为什么报错", RouteKind.work),
    ("把这段逻辑重构得清楚一点", RouteKind.work),
    ("你好，今天想随便聊聊", RouteKind.speak),
    ("陪我说会话吧", RouteKind.speak),
    ("你现在在想什么", RouteKind.speak),
    ("我有点累，想听你说两句", RouteKind.speak),
    ("我们聊聊这个想法的感觉", RouteKind.speak),
    ("刚刚那句话是什么意思", RouteKind.speak),
)


@dataclass(frozen=True)
class RouteSample:
    id: str
    text: str
    label: RouteKind
    embedding: list[float]
    source: str
    session_id: str = ""
    predicted: str = ""
    corrected: bool = False

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "label": self.label.value,
            "embedding": list(self.embedding),
            "source": self.source,
            "session_id": self.session_id,
            "predicted": self.predicted,
            "corrected": self.corrected,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RouteSample:
        return cls(
            id=str(row.get("id", "")),
            text=str(row.get("text", "")),
            label=RouteKind(str(row.get("label", RouteKind.speak.value))),
            embedding=[float(v) for v in row.get("embedding", [])],
            source=str(row.get("source", "")),
            session_id=str(row.get("session_id", "")),
            predicted=str(row.get("predicted", "")),
            corrected=bool(row.get("corrected", False)),
        )


class InboundRouteStore:
    def __init__(self, root: str) -> None:
        storage = JsonStorageService(root)
        self._samples = storage.collection("route_samples")
        self._weights = storage.collection("route_weights")
        self._sessions = storage.collection("route_sessions")
        self._pierces = storage.collection("route_pierces")
        self._meta = storage.collection("route_meta")

    def samples(self) -> list[RouteSample]:
        return [
            RouteSample.from_row(row)
            for row in self._samples.all()
            if row.get("embedding") and row.get("label")
        ]

    def gold_count(self) -> int:
        return len(self.samples())

    def add_sample(
        self,
        *,
        text: str,
        label: RouteKind,
        embedding: list[float],
        source: str,
        session_id: str = "",
        predicted: RouteKind | None = None,
        sample_id: str = "",
    ) -> RouteSample:
        sid = sample_id.strip() or str(uuid.uuid4())
        sample = RouteSample(
            id=sid,
            text=text.strip(),
            label=label,
            embedding=[float(v) for v in embedding],
            source=source,
            session_id=session_id.strip(),
            predicted=(predicted.value if predicted is not None else label.value),
            corrected=predicted is not None and predicted != label,
        )
        self._samples.upsert(sid, sample.to_row())
        return sample

    def update_sample_label(
        self,
        sample_id: str,
        *,
        true_label: RouteKind,
        predicted: RouteKind,
    ) -> RouteSample:
        row = self._samples.get(sample_id)
        if row is None:
            raise KeyError(f"unknown route sample: {sample_id}")
        row["label"] = true_label.value
        row["predicted"] = predicted.value
        row["corrected"] = True
        self._samples.upsert(sample_id, row)
        return RouteSample.from_row(row)

    def record_pierce(
        self,
        *,
        session_id: str,
        sample_id: str,
        previous: RouteKind,
        true_label: RouteKind,
        text: str,
    ) -> None:
        pid = str(uuid.uuid4())
        self._pierces.upsert(pid, {
            "id": pid,
            "session_id": session_id,
            "sample_id": sample_id,
            "previous": previous.value,
            "true_label": true_label.value,
            "text": text,
        })

    def session_route(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    def set_session_route(
        self,
        session_id: str,
        *,
        route: RouteKind,
        question: str,
        sample_id: str,
        source: str,
    ) -> None:
        self._sessions.upsert(session_id, {
            "session_id": session_id,
            "route": route.value,
            "question": question,
            "sample_id": sample_id,
            "source": source,
        })

    def first_request_count(self) -> int:
        row = self._meta.get("counter") or {}
        return int(row.get("first_request_count", 0))

    def increment_first_request_count(self) -> int:
        row = self._meta.get("counter") or {}
        count = int(row.get("first_request_count", 0)) + 1
        row["first_request_count"] = count
        self._meta.upsert("counter", row)
        return count

    def weights(self) -> dict[str, Any] | None:
        return self._weights.get("active")

    def save_weights(self, weights: dict[str, Any]) -> None:
        self._weights.upsert("active", dict(weights))
