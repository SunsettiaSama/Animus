from __future__ import annotations

from typing import TYPE_CHECKING

from .blocks.guidance.session_bridge import (
    render_interrupt_system_block,
    resolve_social_user_text,
)

if TYPE_CHECKING:
    from agent.soul.speak.io.outbound.stream import SpeakAgentOutput
    from agent.soul.speak.session.queue.types import InterruptContext

    from .bundle import SpeakPromptBundle

APPEND_CONTINUE_INSTRUCTION = (
    "请继续完成本轮尚未说完的内容；输出仍需包含 [think]…[/think] 与 "
    "[state]finish[/state]（或 [state]append[/state]）。"
)


def build_turn_system(
    bundle: SpeakPromptBundle,
    *,
    interrupt_context: InterruptContext | None = None,
    round_idx: int = 0,
    partial_output: str = "",
    parsed: SpeakAgentOutput | None = None,
) -> str:
    system = bundle.build_system()
    if interrupt_context is not None:
        system = f"{system}\n\n{render_interrupt_system_block(interrupt_context)}"
    if round_idx > 0 and parsed is not None and parsed.session_state == "append":
        system = f"{system}\n\n{APPEND_CONTINUE_INSTRUCTION}"
        if partial_output.strip():
            system = f"{system}\n\n已输出片段如下，请接着说完、不要重复：\n{partial_output.strip()}"
    brew_hint = bundle.meta.get("recent_brew_lines")
    if isinstance(brew_hint, str) and brew_hint.strip():
        system = f"{system}\n\n请勿重复以下内容：{brew_hint.strip()}"
    return system


def resolve_llm_user_text(
    bundle: SpeakPromptBundle,
    user_text: str,
    *,
    round_idx: int = 0,
    parsed: SpeakAgentOutput | None = None,
) -> str:
    if round_idx > 0 and parsed is not None and parsed.session_state == "append":
        return "请接着说完，不要重复已输出内容。"
    return resolve_social_user_text(bundle, user_text)
