from __future__ import annotations

import importlib
from typing import Any

from .distill import (
    PERSONA_DISTILL_SCHEMA_VERSION,
    PersonaDistillPack,
    PersonaDistillWriter,
    ensure_distill,
    render_dialogue_block,
)
from .profile.block import ProfileBlock
from .profile.profile import PersonaProfile
from .profile.store import ProfileStore
from .self_concept.block import SelfConceptBlock

_LAZY: dict[str, str] = {
    "PersonaManager": ".manager",
    "PersonaService": ".service",
    "BufferMeta": ".buffer",
    "ClusterSignal": ".buffer",
    "ExperienceBuffer": ".buffer",
    "ExperienceBufferStore": ".buffer",
    "MonthlyDriftUpdater": ".buffer",
}

__all__ = [
    "PersonaManager",
    "PersonaService",
    "BufferMeta",
    "ClusterSignal",
    "ExperienceBuffer",
    "ExperienceBufferStore",
    "MonthlyDriftUpdater",
    "ProfileBlock",
    "PersonaProfile",
    "ProfileStore",
    "SelfConceptBlock",
    "PERSONA_DISTILL_SCHEMA_VERSION",
    "PersonaDistillPack",
    "PersonaDistillWriter",
    "ensure_distill",
    "render_dialogue_block",
]


def __getattr__(name: str) -> Any:
    rel = _LAZY.get(name)
    if rel is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(rel, __name__)
    return getattr(mod, name)
