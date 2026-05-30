from __future__ import annotations

from agent.soul.speak.compose.system import build_system_prompt
from agent.soul.speak.compose.reply_style import SpeakReplyStyle


def test_inbound_role_mentions_live_session_window():
    system = build_system_prompt(
        mode="inbound",
        output_format=SpeakReplyStyle().render_prompt(),
    )
    assert "发起了会话" in system.role
    assert "即时" in system.role
