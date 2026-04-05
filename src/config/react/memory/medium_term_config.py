from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MediumTermMemoryConfig:
    summary_trigger_steps: int = 4
    max_summary_tokens: int = 400
