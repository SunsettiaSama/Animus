from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MilestoneConfig:
    enabled: bool = False
    milestone_dir: str = ""
    max_milestones: int = 50
    importance_threshold: float = 0.6
    max_keywords: int = 5
    max_summary_chars: int = 200
    max_detail_chars: int = 1000
    top_k_retrieve: int = 2
    inject_detail: bool = True
    prompt_header: str = "## 重要里程碑"

    @classmethod
    def from_dict(cls, d: dict) -> MilestoneConfig:
        return cls(
            enabled=bool(d.get("enabled", False)),
            milestone_dir=d.get("milestone_dir", ""),
            max_milestones=int(d.get("max_milestones", 50)),
            importance_threshold=float(d.get("importance_threshold", 0.6)),
            max_keywords=int(d.get("max_keywords", 5)),
            max_summary_chars=int(d.get("max_summary_chars", 200)),
            max_detail_chars=int(d.get("max_detail_chars", 1000)),
            top_k_retrieve=int(d.get("top_k_retrieve", 2)),
            inject_detail=bool(d.get("inject_detail", True)),
            prompt_header=d.get("prompt_header", "## 重要里程碑"),
        )
