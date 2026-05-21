from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ClusterSignal:
    """Persona buffer 元数据：记录聚类主题与调度时间，不存记忆正文。

    记忆检索、遗忘、迭代由 Memory 模块负责；月度更新时按 ``theme`` + ``unit_ids`` 回查 Memory。
    """

    theme: str
    tick_id: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: str = field(default_factory=_now_iso)
    consolidated: bool = False
    consolidated_at: str = ""
    cluster_key: str = ""
    unit_ids: list[str] = field(default_factory=list)
    mass: float = 0.0
    span_days: float = 0.0
    recurrence: int = 0
    cohesion: float = 0.0
    persona_score: float = 0.0
    long_term_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "theme": self.theme,
            "tick_id": self.tick_id,
            "recorded_at": self.recorded_at,
            "consolidated": self.consolidated,
            "consolidated_at": self.consolidated_at,
            "cluster_key": self.cluster_key,
            "unit_ids": list(self.unit_ids),
            "mass": self.mass,
            "span_days": self.span_days,
            "recurrence": self.recurrence,
            "cohesion": self.cohesion,
            "persona_score": self.persona_score,
            "long_term_ratio": self.long_term_ratio,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ClusterSignal:
        raw_ids = d.get("unit_ids") or []
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            theme=str(d.get("theme", "")).strip(),
            tick_id=str(d.get("tick_id", "")),
            recorded_at=d.get("recorded_at") or d.get("ts") or _now_iso(),
            consolidated=bool(d.get("consolidated", False)),
            consolidated_at=str(d.get("consolidated_at", "")),
            cluster_key=str(d.get("cluster_key", "")),
            unit_ids=[str(x) for x in raw_ids if str(x).strip()],
            mass=float(d.get("mass") or 0.0),
            span_days=float(d.get("span_days") or 0.0),
            recurrence=int(d.get("recurrence") or 0),
            cohesion=float(d.get("cohesion") or 0.0),
            persona_score=float(d.get("persona_score") or 0.0),
            long_term_ratio=float(d.get("long_term_ratio") or 0.0),
        )

    @classmethod
    def from_cluster_meta(cls, payload: dict) -> ClusterSignal:
        """从 Memory.persona_clusters 产出的 buffer 元数据构造。"""
        theme = str(payload.get("theme", "")).strip()
        if not theme:
            raise ValueError("cluster buffer meta requires non-empty theme")
        signal = cls.from_dict(payload)
        signal.theme = theme
        signal.tick_id = str(payload.get("tick_id", signal.tick_id))
        return signal
