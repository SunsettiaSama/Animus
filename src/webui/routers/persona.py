from __future__ import annotations

import json
import os

from fastapi import APIRouter
from pydantic import BaseModel

from state import get_state

router = APIRouter()


class PersonaSaveRequest(BaseModel):
    enabled: bool = False
    name: str = "Assistant"
    background: str = ""
    traits: list[str] = []
    values: list[str] = []
    style: str = ""
    max_profile_chars: int = 500
    evolution_enabled: bool = False
    evolve_interval: int = 1
    skills_enabled: bool = True
    max_skills_in_prompt: int = 5
    max_skills_chars: int = 600
    reflection_enabled: bool = False
    reflect_interval: int = 3
    max_reflection_chars: int = 400


def _load_persona_cfg_dict() -> dict:
    state = get_state()
    if not os.path.exists(state.persona_cfg_file):
        return {}
    with open(state.persona_cfg_file, encoding="utf-8") as f:
        return json.load(f)


@router.get("/api/persona")
def get_persona():
    from agent.soul.persona.profile.store import ProfileStore
    state = get_state()
    store   = ProfileStore(state.persona_dir)
    profile = store.load_profile()
    d       = _load_persona_cfg_dict()
    return {
        "enabled":              d.get("enabled", False),
        "profile":              profile.to_dict(),
        "max_profile_chars":    d.get("max_profile_chars", 500),
        "evolution_enabled":    d.get("evolution_enabled", False),
        "evolve_interval":      d.get("evolve_interval", 1),
        "skills_enabled":       d.get("skills_enabled", True),
        "max_skills_in_prompt": d.get("max_skills_in_prompt", 5),
        "max_skills_chars":     d.get("max_skills_chars", 600),
        "reflection_enabled":   d.get("reflection_enabled", False),
        "reflect_interval":     d.get("reflect_interval", 3),
        "max_reflection_chars": d.get("max_reflection_chars", 400),
    }


@router.post("/api/persona/save")
def save_persona(req: PersonaSaveRequest):
    from agent.soul.persona.profile.profile import PersonaProfile
    from agent.soul.persona.profile.store import ProfileStore
    state = get_state()
    os.makedirs(state.persona_dir, exist_ok=True)
    store = ProfileStore(state.persona_dir)
    store.save_profile(PersonaProfile(
        name=req.name,
        background=req.background,
        traits=req.traits,
        values=req.values,
        style=req.style,
    ))
    cfg_data = {
        "enabled":              req.enabled,
        "max_profile_chars":    req.max_profile_chars,
        "evolution_enabled":    req.evolution_enabled,
        "evolve_interval":      req.evolve_interval,
        "skills_enabled":       req.skills_enabled,
        "max_skills_in_prompt": req.max_skills_in_prompt,
        "max_skills_chars":     req.max_skills_chars,
        "reflection_enabled":   req.reflection_enabled,
        "reflect_interval":     req.reflect_interval,
        "max_reflection_chars": req.max_reflection_chars,
    }
    with open(state.persona_cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg_data, f, ensure_ascii=False, indent=2)
    return {"status": "ok"}
