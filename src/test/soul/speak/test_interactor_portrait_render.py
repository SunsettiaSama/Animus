from __future__ import annotations

from agent.soul.speak.compose.interactor_portrait.render import (
    render_interactor_portrait_for_prompt,
)


def test_portrait_prompt_uses_placeholder_not_uuid():
    text = render_interactor_portrait_for_prompt(
        name="",
        core_traits=[],
        portrait_body="",
        agent_relation="",
        recent_impression="",
    )
    assert "7a4e564d" not in text
    assert "称呼：暂无" in text
    assert "特质：暂无" in text
    assert "【对话者画像】" in text


def test_portrait_prompt_includes_name_and_traits():
    text = render_interactor_portrait_for_prompt(
        name="荧",
        core_traits=["旅行者", "直率"],
        agent_relation="老朋友",
        recent_impression="爱开玩笑",
    )
    assert "称呼：荧" in text
    assert "旅行者" in text
    assert "与你的关系：老朋友" in text
    assert "近期印象：爱开玩笑" in text
