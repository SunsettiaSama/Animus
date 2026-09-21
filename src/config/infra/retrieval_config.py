"""infra.retrieval 配置：rewriter / growth / locator / walk。"""
from __future__ import annotations

import yaml
from dataclasses import dataclass

from infra.retrieval.growth import GrowthConfig as _GrowthConfig
from infra.retrieval.locate import LocatorConfig as _LocatorConfig


@dataclass
class RewriterConfig:
    enabled: bool = True
    cache_size: int = 512


@dataclass
class WalkOptions:
    beam_width: int = 3
    max_nodes: int = 10
    w_semantic: float = 0.6
    w_edge: float = 0.4
    hop_decay: float = 0.05
    min_step_score: float = 0.0


@dataclass
class RetrievalConfig:
    rewriter: RewriterConfig
    growth: _GrowthConfig
    locator: _LocatorConfig
    walk: WalkOptions
    store_root: str = ".react/retrieval"  # 模板/统计/locator 持久化目录

    @classmethod
    def from_dict(cls, d: dict) -> "RetrievalConfig":
        d = d or {}
        rw = d.get("rewriter") or {}
        gr = d.get("growth") or {}
        lo = d.get("locator") or {}
        wa = d.get("walk") or {}
        return cls(
            rewriter=RewriterConfig(
                enabled=bool(rw.get("enabled", True)),
                cache_size=int(rw.get("cache_size", 512)),
            ),
            growth=_GrowthConfig(
                enabled=bool(gr.get("enabled", True)),
                authoring_enabled=bool(gr.get("authoring_enabled", True)),
                hit_threshold=float(gr.get("hit_threshold", 0.25)),
                min_samples=int(gr.get("min_samples", 20)),
                cooldown_minutes=float(gr.get("cooldown_minutes", 30.0)),
                retire_threshold=float(gr.get("retire_threshold", 0.10)),
                max_templates=int(gr.get("max_templates", 64)),
            ),
            locator=_LocatorConfig(
                enabled=bool(lo.get("enabled", True)),
                scale_threshold=int(lo.get("scale_threshold", 10_000)),
                centers=int(lo.get("centers", 1000)),
                probe_top_m=int(lo.get("probe_top_m", 4)),
                max_iter=int(lo.get("max_iter", 50)),
                seed=int(lo.get("seed", 0)),
                refit_drift_ratio=float(lo.get("refit_drift_ratio", 0.1)),
            ),
            walk=WalkOptions(
                beam_width=int(wa.get("beam_width", 3)),
                max_nodes=int(wa.get("max_nodes", 10)),
                w_semantic=float(wa.get("w_semantic", 0.6)),
                w_edge=float(wa.get("w_edge", 0.4)),
                hop_decay=float(wa.get("hop_decay", 0.05)),
                min_step_score=float(wa.get("min_step_score", 0.0)),
            ),
            store_root=str(d.get("store_root", ".react/retrieval")),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "RetrievalConfig":
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def load_default(cls, path: str | None = None) -> "RetrievalConfig":
        if path is None:
            from config import paths

            path = str(paths.retrieval_config_yaml)
        try:
            return cls.from_yaml(path)
        except FileNotFoundError:
            return cls.from_dict({})
