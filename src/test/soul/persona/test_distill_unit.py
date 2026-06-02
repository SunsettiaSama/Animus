from __future__ import annotations

from agent.soul.persona.distill import (
    PERSONA_DISTILL_SCHEMA_VERSION,
    PersonaDistillPack,
    PersonaDistillStore,
    PersonaDistillWriter,
    ensure_distill,
    render_dialogue_block,
)
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.concept import Belief, BeliefStrength, SelfConcept
from agent.soul.speak.orchestrator.persona import collect_persona_layer
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill


def test_persona_distill_pack_roundtrip():
    dialogue = (
        "你是莉奈娅，边境探险队的记录者。你说话不急，习惯先听清对方再开口�?
    )
    pack = PersonaDistillPack(
        source_revision="built|sc",
        slices={
            "general": "g",
            "dialogue": dialogue,
            "story": "s",
            "reasoning": "r",
            "memory_anchor": "m",
        },
    )
    restored = PersonaDistillPack.from_dict(pack.to_dict())
    assert restored.schema_version == PERSONA_DISTILL_SCHEMA_VERSION
    assert restored.is_current("built|sc")
    assert render_dialogue_block(restored) == dialogue


def test_ensure_distill_cache_hit(tmp_path):
    profile = PersonaProfile(name="T", core_traits=["冷静"], built=True, built_at="t1")
    concept = SelfConcept(narrative="陪伴�?)
    revision = "t1|"
    dialogue = "你是 T，冷静而克制。你说话简短，先听再说�?
    pack = PersonaDistillPack(
        source_revision=revision,
        slices={
            "general": "你是 T，冷静而克制�?,
            "dialogue": dialogue,
            "story": "s",
            "reasoning": "r",
            "memory_anchor": "m",
        },
    )
    PersonaDistillStore(str(tmp_path)).save(pack)

    result = ensure_distill(
        persona_dir=str(tmp_path),
        profile=profile,
        self_concept=concept,
        attention_keywords=[],
        source_revision=revision,
        llm=None,
    )
    assert result.refreshed is False
    assert result.reason == "cache_hit"
    assert result.pack is not None
    assert result.pack.dialogue_text() == dialogue


def test_distill_writer_five_llm_calls():
    profile = PersonaProfile(
        name="莉奈�?,
        core_traits=["好奇"],
        interpersonal_style="温和",
        built=True,
        built_at="b1",
    )
    concept = SelfConcept(
        narrative="我是探险队的记录者�?,
        beliefs=[
            Belief(content="认真倾听很重�?, strength=BeliefStrength.established),
        ],
    )
    responses = {
        "general": "你是莉奈娅，好奇而温和，重视倾听�?,
        "dialogue": (
            "你是莉奈娅，边境探险队的记录者。你说话不急，习惯先听清对方再开口；"
            "语气平稳偏亲近，少花哨。你不爱说教，没把握时会先确认事实�?
        ),
        "story": "你长期在探险队记录航行与营地夜晚�?,
        "reasoning": "你更习惯先搭整体框架，再补细节�?,
        "memory_anchor": "你是探险队的记录者，习惯先倾听再整理线索�?,
    }

    class _LLM:
        def __init__(self) -> None:
            self.calls = 0

        def generate_messages(self, messages):
            self.calls += 1
            system = messages[0].content
            for slice_id, text in responses.items():
                if f"「{slice_id}�? in messages[1].content:
                    return text
            raise AssertionError(f"unexpected slice in prompt: {messages[1].content[:80]}")

    llm = _LLM()
    pack = PersonaDistillWriter(llm).distill(
        profile,
        concept,
        attention_keywords=["探险"],
        source_revision="b1|",
    )
    assert llm.calls == 5
    assert pack.slice("general") == responses["general"]
    assert pack.dialogue_text().startswith("你是莉奈�?)
    assert "语调" not in pack.dialogue_text()


def test_collect_persona_from_distill_snapshot():
    snap = persona_snapshot_with_distill(name="A")
    injected = collect_persona_layer(persona_snap=snap)
    assert "A" in injected.self_narrative
    assert "冷静" in injected.stable_portrait