from __future__ import annotations

import json

from agent.soul.presence.service import PresenceService
from agent.soul.presence.transition.dialogue import (
    DialogueBlock,
    DialogueFsmRefresher,
    DialogueSessionTransition,
    is_user_agent_dialogue,
)
from config.soul.presence.config import DIALOGUE_FSM_REFRESH_EVERY_K as K
from agent.soul.presence.experience.pipeline import PresenceExperiencePipeline
from agent.soul.speak.bridge import SpeakDialogueBridge
from agent.soul.speak.chunk import SpeakSubjectiveChunk, SpeakTurnChunk
from agent.soul.presence.fsm.state import PresenceState


class _RefreshLLM:
    def generate_messages(self, messages, **kwargs) -> str:
        return json.dumps(
            {
                "affect": "对话推进后我更专注。",
                "somatic": "肩背仍有些紧。",
                "working_memory": "用户还在等架构结论。",
                "thinking": "我在组织下一层说明。",
                "perception": "对方语气比刚才更急。",
            },
            ensure_ascii=False,
        )


def test_is_user_agent_dialogue_requires_user_text():
    assert is_user_agent_dialogue(DialogueBlock(user_text="你好", agent_text="嗯"))
    assert not is_user_agent_dialogue(DialogueBlock(user_text="", agent_text="我先说"))


def test_dialogue_transition_refreshes_every_k_blocks():
    state = PresenceState()
    transition = DialogueSessionTransition(
        refresher=DialogueFsmRefresher(_RefreshLLM()),
        interval=K,
    )

    for index in range(K - 1):
        result = transition.observe(
            state,
            DialogueBlock(user_text=f"u{index}", agent_text=f"a{index}"),
            session_id="tao",
        )
        assert result.counted is True
        assert result.refreshed is False

    result = transition.observe(
        state,
        DialogueBlock(user_text="u-final", agent_text="a-final"),
        session_id="tao",
    )
    assert result.refreshed is True
    assert result.refresh is not None
    assert result.refresh.source == "llm"
    assert "专注" in state.affect.narrative
    assert "更急" in state.perception.narrative


def test_finalize_exports_continuous_experience(tmp_path):
    presence = PresenceService(
        life_dir=str(tmp_path),
        dialogue_refresher=DialogueFsmRefresher(_RefreshLLM()),
    )
    presence.observe_dialogue_turn("tao", user_text="快点", agent_text="好的，分三步")
    experience = presence.finalize_dialogue_experience("tao")
    assert experience is not None
    assert "更急" in experience.perception
    assert "组织" in experience.narration
    assert presence._dialogue_transition.block_count("tao") == 0


def test_presence_observe_dialogue_turn_persists_on_refresh(tmp_path):
    svc = PresenceService(
        life_dir=str(tmp_path),
        dialogue_refresher=DialogueFsmRefresher(_RefreshLLM()),
    )
    for index in range(K):
        svc.observe_dialogue_turn(
            "tao",
            user_text=f"q{index}",
            agent_text=f"a{index}",
        )
    snap = svc.snapshot("tao")
    assert "专注" in snap.state.affect.narrative


def test_speak_bridge_triggers_dialogue_block_counter():
    svc = PresenceService(dialogue_refresher=DialogueFsmRefresher(_RefreshLLM()))
    pipeline = PresenceExperiencePipeline(life_dir="")
    subj = SpeakSubjectiveChunk(perception="用户追问", narration="我解释边界")
    bridge = SpeakDialogueBridge(
        on_dialogue_turn=lambda **kwargs: pipeline.dialogue.record_dialogue_turn(svc, **kwargs),
    )

    for index in range(K):
        bridge.record_turn(
            SpeakTurnChunk(
                session_id="tao",
                user_text=f"问{index}",
                agent_text=f"答{index}",
                subjective=subj,
            )
        )

    assert "专注" in svc.snapshot("tao").state.affect.narrative


def test_agent_only_block_does_not_count():
    transition = DialogueSessionTransition(interval=K)
    state = PresenceState()
    result = transition.observe(
        state,
        DialogueBlock(user_text="", agent_text="我自驱补充一句"),
        session_id="tao",
    )
    assert result.counted is False
    assert transition.block_count("tao") == 0
