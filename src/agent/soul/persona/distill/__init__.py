"""Persona 蒸馏子画像：角色 Speak 用 dialogue；导演 Speak 用 director。"""

from .ensure import DistillEnsureResult, ensure_distill
from .render import render_dialogue_block, render_dialogue_from_snapshot
from .schema import PERSONA_DISTILL_SCHEMA_VERSION, SLICE_IDS, PersonaDistillPack
from .store import PersonaDistillStore
from .writer import PersonaDistillWriter

__all__ = [
    "PERSONA_DISTILL_SCHEMA_VERSION",
    "SLICE_IDS",
    "DistillEnsureResult",
    "PersonaDistillPack",
    "PersonaDistillStore",
    "PersonaDistillWriter",
    "ensure_distill",
    "render_dialogue_block",
    "render_dialogue_from_snapshot",
]
