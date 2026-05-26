from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.speak.compose import SpeakInjectedContext, SpeakPromptComposer, SpeakSystemPrompt
from agent.soul.speak.compose.share_queue import evaluate_share_prompt
from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue


def test_compose_persona_and_presence_fields_separated():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = {
        "profile": {
            "name": "小A",
            "core_traits": ["温和", "好奇"],
            "values": ["真诚"],
        },
        "self_concept": {
            "narrative": "我在学习如何更好地陪伴用户。",
            "beliefs": [
                {"content": "认真倾听很重要", "strength": "established"},
            ],
        },
    }
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = "平静"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = "在想如何回答"
    snap.state.perception.render.return_value = "用户刚发来问候"
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    presence.snapshot.return_value = snap

    bundle = SpeakPromptComposer(persona, presence).compose("tao", "你好")
    system = bundle.build_system()

    assert isinstance(bundle.injected, SpeakInjectedContext)
    assert isinstance(bundle.system, SpeakSystemPrompt)
    assert "【人物画像】小A" in system
    assert "【自我认知】" in system
    assert "【当下态·静态】" in system
    assert "情感：平静" in system
    assert "你有想要分享的内容" not in system
    assert "presence_self_narrative" not in system


def test_compose_injects_share_desire_and_summary():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = {"profile": {"name": "小A"}, "self_concept": {}}
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {
        "share_queue": ShareIntentQueue(
            items=[ShareIntent(topic="今天的架构进展", share_desire=ShareDesire.moderate)],
        ).to_dict(),
    }
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.moderate
    presence.snapshot.return_value = snap

    bundle = SpeakPromptComposer(persona, presence).compose("tao", "你好")
    system = bundle.build_system()

    assert bundle.wants_share is True
    assert "你有想要分享的内容。" in system
    assert "分享摘要：" in system
    assert "架构进展" in system


def test_evaluate_share_prompt_without_queue():
    snap = MagicMock()
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none

    hint = evaluate_share_prompt(snap)
    assert hint.wants_share is False
    assert hint.summary == ""
