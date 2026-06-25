from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.soul.persona.distill import PERSONA_DISTILL_SCHEMA_VERSION, PersonaDistillWriter
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.concept import SelfConcept
from agent.soul.persona.render_voice import (
    render_main_profile_from_snap,
    render_self_concept_from_snap,
)
from agent.soul.speak.pipelines.request_driven.orchestrator.system import build_system_layer
from agent.soul.speak.pipelines.request_driven.orchestrator.system.output_format import SpeakOutputFormat
from agent.soul.speak.io.outbound.stream import parse_agent_output
from agent.soul.speak.llm.engine import SpeakLLMEngine
from test.soul.persona._api_llm import api_llm_from_env

pytestmark = pytest.mark.persona_distill_api

_FIXTURE = Path(__file__).parent / "fixtures" / "rich_built_profile.json"


def _load_fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.persona_distill_api
def test_distill_slices_shorter_than_full_render(tmp_path):
    data = _load_fixture()
    profile = PersonaProfile.from_dict(data["profile"])
    concept = SelfConcept.from_dict(data["self_concept"])
    keywords = list(data.get("attention_keywords") or [])

    llm = api_llm_from_env()
    revision = f"{profile.built_at}|{concept.updated_at}"
    pack = PersonaDistillWriter(llm).distill(
        profile,
        concept,
        attention_keywords=keywords,
        source_revision=revision,
    )

    full_len = len(
        render_main_profile_from_snap(
            {"profile": data["profile"]},
            caller="test_distill_api",
        )
    ) + len(
        render_self_concept_from_snap(
            {"self_concept": data["self_concept"]},
            caller="test_distill_api",
        )
    )
    slice_len = sum(len(pack.slice(k)) for k in ("general", "dialogue", "story", "reasoning", "memory_anchor"))
    assert pack.schema_version == PERSONA_DISTILL_SCHEMA_VERSION
    assert pack.source_revision == revision
    assert slice_len < full_len
    assert 120 <= len(pack.dialogue_text()) <= 280
    assert pack.dialogue_text().startswith("?)


@pytest.mark.persona_distill_api
def test_speak_roleplay_with_dialogue_slice_only():
    data = _load_fixture()
    profile = PersonaProfile.from_dict(data["profile"])
    concept = SelfConcept.from_dict(data["self_concept"])
    llm = api_llm_from_env()
    revision = f"{profile.built_at}|{concept.updated_at}"
    pack = PersonaDistillWriter(llm).distill(
        profile,
        concept,
        attention_keywords=list(data.get("attention_keywords") or []),
        source_revision=revision,
    )
    dialogue = pack.dialogue_text()
    system = build_system_layer(
        mode="inbound",
        output_format=SpeakOutputFormat(max_fragments=3).render_prompt(),
    )
    system_text = f"{system.role}\n\n{system.output_format}\n\n{dialogue}"

    engine = SpeakLLMEngine(llm)
    raw = engine.generate(
        "请用你自己的口吻介绍你是谁，并说一句你会怎么跟我说话?,
        system=system_text,
    ).text
    parsed = parse_agent_output(raw)
    assert parsed.speak.strip() or parsed.thought.strip()
    log_dir = Path("tmp")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "persona_distill_smoke.log"
    log_path.write_text(
        f"=== dialogue ({len(dialogue)} chars) ===\n{dialogue}\n\n"
        f"=== raw response ===\n{raw}\n",
        encoding="utf-8",
    )


@pytest.mark.persona_distill_api
def test_minimal_profile_distill_differs_from_rich():
    llm = api_llm_from_env()
    rich = _load_fixture()
    rich_profile = PersonaProfile.from_dict(rich["profile"])
    rich_concept = SelfConcept.from_dict(rich["self_concept"])

    minimal_profile = PersonaProfile(name="Assistant", core_traits=[], built=True, built_at="min")
    minimal_concept = SelfConcept()

    rich_pack = PersonaDistillWriter(llm).distill(
        rich_profile,
        rich_concept,
        attention_keywords=[],
        source_revision="rich|",
    )
    min_pack = PersonaDistillWriter(llm).distill(
        minimal_profile,
        minimal_concept,
        attention_keywords=[],
        source_revision="min|",
    )
    assert rich_pack.dialogue_text().strip()
    assert min_pack.dialogue_text().strip()
    assert rich_pack.dialogue_text() != min_pack.dialogue_text()
