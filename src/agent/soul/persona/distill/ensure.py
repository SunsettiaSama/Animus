from __future__ import annotations

from dataclasses import dataclass

from infra.llm import BaseLLM

from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.concept import SelfConcept

from .schema import PersonaDistillPack
from .store import PersonaDistillStore
from .writer import PersonaDistillWriter


@dataclass
class DistillEnsureResult:
    pack: PersonaDistillPack | None
    refreshed: bool
    reason: str


def ensure_distill(
    *,
    persona_dir: str,
    profile: PersonaProfile,
    self_concept: SelfConcept,
    attention_keywords: list[str],
    source_revision: str,
    llm: BaseLLM | None,
    force: bool = False,
) -> DistillEnsureResult:
    store = PersonaDistillStore(persona_dir)
    cached = store.load()
    cache_ready = (
        cached is not None
        and cached.is_current(source_revision)
        and cached.dialogue_text()
    )
    # 缺 director 切片时，有 LLM 则重蒸（旧包迁移）；无 LLM 仍可沿用 dialogue。
    missing_director = cache_ready and not cached.director_text()
    if not force and cache_ready and not (missing_director and llm is not None):
        return DistillEnsureResult(pack=cached, refreshed=False, reason="cache_hit")

    if llm is None:
        if cached is not None and cached.dialogue_text():
            return DistillEnsureResult(pack=cached, refreshed=False, reason="no_llm_use_stale")
        return DistillEnsureResult(pack=None, refreshed=False, reason="no_llm")

    writer = PersonaDistillWriter(llm)
    pack = writer.distill(
        profile,
        self_concept,
        attention_keywords=attention_keywords,
        source_revision=source_revision,
    )
    store.save(pack)
    return DistillEnsureResult(pack=pack, refreshed=True, reason="distilled")
