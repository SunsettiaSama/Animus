from __future__ import annotations

from agent.soul.speak.io.outbound.character import (
    CallableCharacterWorkPort,
    CharacterHelpRequest,
    CharacterWorkGateway,
    NoopCharacterWorkPort,
)
from agent.soul.speak.responders.request_driven.interpreter import interpret_role_packet
from agent.soul.speak.responders.request_driven.layers import RoleStaticLayer
from agent.soul.speak.responders.request_driven.orchestrator.prompt_stitch import (
    assemble_character_system,
    assemble_turn_system,
)
from agent.soul.speak.responders.request_driven.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.layer import (
    SpeakSystemLayer,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.output_format import (
    SpeakOutputFormat,
)
from agent.soul.speak.responders.request_driven.character import CharacterAgentHost


def test_character_system_excludes_compose_action_protocol():
    fmt = SpeakOutputFormat().render_prompt()
    assert "[action]" in fmt or "action" in fmt.lower()
    bundle = SpeakPromptBundle(
        session_id="s1",
        system=SpeakSystemLayer(
            role="你是角色。",
            output_format=fmt,
        ),
    )
    full = assemble_turn_system(bundle, include_output_format=True)
    character = assemble_character_system(bundle)
    assert "你是角色" in character
    assert fmt not in character
    assert fmt in full


def test_role_static_only_prompts_short_speak():
    static = RoleStaticLayer()
    assert "<speak>一条短消息</speak>" in static.protocol
    assert "短消息" in static.protocol
    assert 'i="' not in static.protocol
    assert "emit" not in static.protocol
    assert "ask help" not in static.protocol


def test_interpret_ask_help_separate_from_timeline():
    raw = (
        "<ask help>帮我查一下明天天气趋势</ask help>\n"
        "<speak context>我先想想。</speak context>\n"
        "<speak action>emit</speak action>"
    )
    packet = interpret_role_packet(raw)
    assert packet.help_goals == ("帮我查一下明天天气趋势",)
    assert "我先想想" in packet.timeline.answer_text


def test_character_work_gateway_routes_natural_language_only():
    seen: list[str] = []

    def _runner(goal, *, session_id="", user_text=""):
        seen.append(goal)
        assert "web_search" not in goal
        return {"ok": True, "observation": f"结果:{goal}"}

    gw = CharacterWorkGateway(CallableCharacterWorkPort(_runner))
    obs = gw.request_helps(
        session_id="s1",
        goals=("查资料", "第二个不会跑"),
        limit=1,
    )
    assert obs == ("结果:查资料",)
    assert seen == ["查资料"]


def test_noop_work_port_does_not_fabricate_observation():
    gw = CharacterWorkGateway(NoopCharacterWorkPort())
    result = gw.request_help(session_id="s1", goal="x")
    assert result.ok is False
    assert result.observation == ""


def test_character_agent_host_generates_via_fn_without_tool_prompt():
    calls: list[tuple[str, str]] = []

    def _gen(system: str, user: str) -> str:
        calls.append((system, user))
        assert "web_search" not in system.lower()
        assert "<A>" not in system
        return (
            "<speak context>你好</speak context>\n"
            "<speak action>emit</speak action>"
        )

    host = CharacterAgentHost(None, generate_fn=_gen, auto_start=False)
    raw = host.generate(
        system="你是角色。",
        user_text="在吗",
        context_cards=[("对话轨迹", "用户：嗨")],
    )
    assert "你好" in raw
    assert calls
    assert "在吗" in calls[0][1] or "[用户输入]" in calls[0][1]
