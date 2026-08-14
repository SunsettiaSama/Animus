"""system + timeline -> LangChain messages。"""
from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from infra.agent.timeline import Timeline


def build_messages(*, system: str, timeline: Timeline) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    system_text = system.strip()
    if system_text:
        messages.append(SystemMessage(content=system_text))
    human = timeline.render().strip()
    if not human:
        human = "(empty context)"
    messages.append(HumanMessage(content=human))
    return messages
