from __future__ import annotations

from agent.soul.speak.orchestrator.system import build_system_layer
from agent.soul.speak.orchestrator.reply_style import SpeakReplyStyle


def test_inbound_role_mentions_live_session_window():
    system = build_system_layer(
        mode="inbound",
        output_format=SpeakReplyStyle().render_prompt(),
    )
    assert "虚拟世界" in system.role
    assert "发起了会�? in system.role
