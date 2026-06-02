"""Persona 蒸馏子画像：五切片均注入「扮演该角色的 LLM 服务」；Speak 仅用 dialogue。"""

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
