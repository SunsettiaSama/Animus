from __future__ import annotations

from agent.interaction.core import (
    AgentOutputKind,
    InteractionContext,
    SemanticInteraction,
)


def test_three_output_kinds_in_one_interaction():
    ix = SemanticInteraction(context=InteractionContext(session_id="tao"))
    ix.append_user("帮我查风险")
    ix.append_thought("先规划检索路径", step_index=0)
    ix.append_action("web_search", arguments={"q": "risk"}, step_index=1, observation="...")
    ix.append_dialogue("我先查一下资料", final=False)
    ix.append_dialogue("风险有三点", final=True)

    assert len(ix.agent_outputs) == 4
    assert len(ix.outputs_of(AgentOutputKind.thought)) == 1
    assert len(ix.outputs_of(AgentOutputKind.action)) == 1
    assert len(ix.outputs_of(AgentOutputKind.dialogue)) == 2
    assert ix.last_agent_text() == "风险有三点"
    assert "dialogue" in ix.continuity_digest()
    assert ix.outputs_of(AgentOutputKind.action)[0].action.name == "web_search"
