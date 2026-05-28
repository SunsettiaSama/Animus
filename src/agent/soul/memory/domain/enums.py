from __future__ import annotations

from enum import Enum


class Valence(str, Enum):
    positive = "positive"
    negative = "negative"
    mixed = "mixed"
    neutral = "neutral"


class MemoryTier(str, Enum):
    short_term = "short_term"
    long = "long"


class MemoryNetwork(str, Enum):
    social = "social"
    event = "event"


class SocialNodeRole(str, Enum):
    core = "core"
    neighborhood = "neighborhood"


class EdgeType(str, Enum):
    about = "about"
    related_to = "related_to"
    source_of = "source_of"
    weaves = "weaves"
    involves = "involves"


class EvolutionSource(str, Enum):
    manual = "manual"
    dialogue_close = "dialogue_close"
    heartbeat = "heartbeat"
