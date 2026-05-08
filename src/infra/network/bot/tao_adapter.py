from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from config.infra.bot_config import BotConfig


def _format_step_progress(event: Any) -> str:
    thought_raw = (event.thought or "").strip()
    if len(thought_raw) > 120:
        thought_snippet = thought_raw[:120].rsplit(None, 1)[0] + "…"
    else:
        thought_snippet = thought_raw
    obs_raw = (event.observation or "").strip()
    obs_snippet = (obs_raw[:80] + "…") if len(obs_raw) > 80 else obs_raw

    parts = [f"⚙️ 步骤：{event.action}"]
    if thought_snippet:
        parts.append(f"💭 {thought_snippet}")
    if obs_snippet:
        parts.append(f"📎 {obs_snippet}")
    return "\n".join(parts)


class BotTaoAdapter:
    """Translates a ConvLoop event stream into plain-text messages for the Bot layer.

    AgentSession calls messages() and puts each yielded string into its send
    queue.  This class owns all knowledge of TaoEvent concrete types, keeping
    session.py free of agent-layer imports.
    """

    def __init__(self, conv_loop: Any, cfg: BotConfig) -> None:
        self._conv = conv_loop
        self._cfg  = cfg

    def messages(self, question: str) -> Iterator[str]:
        from agent.react.tao import FinishEvent, StepEvent

        for event in self._conv.stream(question):
            if isinstance(event, StepEvent):
                if event.output and event.action != "finish":
                    yield event.output
                if self._cfg.show_step_progress and event.action != "finish":
                    yield _format_step_progress(event)
            elif isinstance(event, FinishEvent):
                if event.answer:
                    yield event.answer
                break

        self._conv.post_process()
