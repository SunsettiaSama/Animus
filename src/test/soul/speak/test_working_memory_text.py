from __future__ import annotations

from agent.soul.speak.io.outbound.stream import parse_agent_output
from agent.soul.speak.session.working_memory_text import format_agent_turn_for_working_memory


def test_format_agent_turn_preserves_speak_action_order():
    parsed = parse_agent_output(
        "[speak]你好。[/speak][action]放下标本[/action][speak]你看这个。[/speak][state]finish[/state]"
    )
    text = format_agent_turn_for_working_memory(parsed.blocks)
    assert text == "你好。\n（动作）放下标本\n你看这个。"


def test_format_agent_turn_speak_fallback():
    assert format_agent_turn_for_working_memory((), speak_fallback="仅对白") == "仅对白"
