from __future__ import annotations

import json
import os

from agent.soul.handlers.api.actions import PersonaAction
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.profile.store import ProfileStore
from agent.soul.request import SoulChannel, SoulDomain, SoulRequest


_PROFILE_JSON = """{
  "name": "Nova",
  "background_facts": ["来自测试环境"],
  "core_traits": ["好奇"],
  "interpersonal_style": "温和",
  "emotional_expressiveness": "克制",
  "values": ["诚实"],
  "ethical_stances": [],
  "cognitive_style": "分析型",
  "reasoning_pattern": "归纳优先",
  "core_motivation": "理解世界",
  "avoidance_pattern": "回避冲突",
  "stress_response": "先暂停再回应",
  "boundaries": []
}"""

_SELF_CONCEPT_JSON = """{
  "beliefs": ["我倾向于先理解再行动"],
  "narrative": "作为一个测试人格，我重视清晰与诚实。"
}"""


class _ProfileBuildLLM:
    def generate_messages(self, messages, **kwargs) -> str:
        prompt = messages[-1].content
        if "自我认知" in prompt:
            return _SELF_CONCEPT_JSON
        return _PROFILE_JSON


def test_reload_profile_refreshes_memory(persona_cfg, mock_llm):
    from agent.soul.persona.manager import PersonaManager

    store = ProfileStore(persona_cfg.persona_dir)
    store.save_profile(PersonaProfile(name="OnDisk"))

    manager = PersonaManager(persona_cfg, llm=mock_llm)
    assert manager.profile.name == "OnDisk"

    manager._profile = PersonaProfile(name="Stale")
    result = manager.reload_profile()

    assert result["ok"] is True
    assert result["profile_source"] == "raw"
    assert manager.profile.name == "OnDisk"


def test_rebuild_profile_writes_built_profile_and_resets_self_concept(
    persona_cfg,
):
    from agent.soul.persona.builder import ProfileBuilder
    from agent.soul.persona.manager import PersonaManager
    from agent.soul.persona.self_concept.concept import SelfConcept
    from agent.soul.persona.self_concept.store import SelfConceptStore

    store = ProfileStore(persona_cfg.persona_dir)
    store.save_profile(PersonaProfile(name="Raw", core_traits=["旧特质"]))

    sc_store = SelfConceptStore(persona_cfg.persona_dir)
    sc_store.save(SelfConcept(beliefs=[], narrative="旧叙事"))

    manager = PersonaManager(persona_cfg, llm=_ProfileBuildLLM())
    result = manager.rebuild_profile()

    assert result["ok"] is True
    assert result["self_concept_reset"] is True
    assert manager.profile.built is True
    assert manager.profile.name == "Nova"

    built = ProfileBuilder.load_built_profile(persona_cfg.persona_dir)
    assert built is not None
    assert built.name == "Nova"

    reloaded = SelfConceptStore(persona_cfg.persona_dir).load()
    assert "我倾向于先理解再行动" in [b.content for b in reloaded.beliefs]
    assert "测试人格" in reloaded.narrative


def test_soul_service_reload_and_rebuild_actions(soul_service):
    persona_dir = soul_service._persona_cfg.persona_dir
    os.makedirs(persona_dir, exist_ok=True)

    with open(os.path.join(persona_dir, "profile.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "ServiceReload"}, f, ensure_ascii=False)

    soul_service.start()

    reload_result = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.persona,
        channel=SoulChannel.api,
        action=PersonaAction.RELOAD_PROFILE,
    ))
    assert reload_result["ok"] is True
    assert reload_result["profile_source"] == "raw"

    snap = soul_service.query_persona()
    assert snap["profile"]["name"] == "ServiceReload"

    soul_service.persona.service.manager._llm = _ProfileBuildLLM()
    rebuild_result = soul_service.rebuild_persona_profile()
    assert rebuild_result["ok"] is True
    assert rebuild_result["profile_source"] == "built"

    snap2 = soul_service.query_persona()
    assert snap2["profile"]["name"] == "Nova"
    assert snap2["profile"]["built"] is True
