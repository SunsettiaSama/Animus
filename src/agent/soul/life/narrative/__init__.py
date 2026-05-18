"""人生叙事：章节弧、叙事事件 / 日志、演化规则、日终综合、LifeProfile（与 ``life.ledger`` 事件类型互不引用）。"""

from .arc import Chapter, StoryArc, StoryArcStore, StoryPhase
from .event import NarrativeEvent, NarrativeEventKind
from .event_log import NarrativeEventLog
from .evolution import (
    NarrativeArcEvolver,
    format_timeline_digest_for_profile,
    infer_story_phase,
    merge_timeline_pairs,
    merged_fact_lines_chronologically,
    narrative_timeline_entries,
)
from .profile import LifeProfile, LifeProfileGenerator, LifeProfileStore
from .synthesis import DailySynthesizer, DailySynthesisResult

__all__ = [
    "Chapter",
    "StoryArc",
    "StoryArcStore",
    "StoryPhase",
    "NarrativeEvent",
    "NarrativeEventKind",
    "NarrativeEventLog",
    "NarrativeArcEvolver",
    "format_timeline_digest_for_profile",
    "infer_story_phase",
    "merge_timeline_pairs",
    "merged_fact_lines_chronologically",
    "narrative_timeline_entries",
    "LifeProfile",
    "LifeProfileGenerator",
    "LifeProfileStore",
    "DailySynthesizer",
    "DailySynthesisResult",
]
