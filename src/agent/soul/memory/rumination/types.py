from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuminationConfig:
    emotion_threshold: float = 0.55
    unfinished_threshold: float = 0.40
    buffer_max_size: int = 64
    gaussian_sigma: float = 0.25
    pool_scan_limit: int = 80
    diffusion_max_hops: int = 2
    diffusion_top_k: int = 5
    diffusion_threshold: float = 0.12


@dataclass
class RuminationBufferEntry:
    node_id: str
    emotion_intensity: float
    unfinished_score: float
    weight: float
    tick_id: str = ""


@dataclass
class RuminationSkillContext:
    node_id: str
    trigger: str
    emotional_context: str = ""
    tick_id: str = ""
    persona_profile: str = ""


@dataclass
class RuminationSkillResult:
    node_id: str
    ran: bool = False
    overwritten: bool = False
    reconstructive_id: str | None = None
    diffusion_ids: list[str] = field(default_factory=list)
    new_edges: list[dict] = field(default_factory=list)
    detail: dict = field(default_factory=dict)
