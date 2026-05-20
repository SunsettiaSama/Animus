from __future__ import annotations

from agent.handler.continuity import ContinuityLlmHandler, parse_continuity_verdict_line

from .signals import ContinuitySignals, build_signals
from .types import ContinuityDecision, ContinuityInput, ContinuityVerdict

_SYSTEM = """你是会话连续性裁决器。判断「用户新消息」是否与「当前交互」仍在同一条语义线上。

只输出两行：
第一行：CONTINUE 或 BREAK（必须大写英文单词之一）
第二行：reason: 简短中文理由

同一任务线的追问、澄清、指代、简短附和 → CONTINUE。
明确换题、无关新任务、放弃当前话题 → BREAK。"""


class LlmContinuityJudge:
    """第三层：外接或本地 LLM handler 裁决灰区。"""

    def __init__(self, llm: ContinuityLlmHandler) -> None:
        self._llm = llm

    def judge(
        self,
        data: ContinuityInput,
        signals: ContinuitySignals | None = None,
    ) -> ContinuityDecision:
        active = data.active
        text = (data.incoming_user_text or "").strip()
        signals = signals or build_signals(data)

        digest = active.continuity_digest() if active is not None else "(无当前交互)"
        user_prompt = (
            f"【当前交互摘要】\n{digest}\n\n"
            f"【期待】{signals.expectation.value if signals.expectation else 'none'}\n\n"
            f"【用户新消息】\n{text}\n"
        )
        raw = self._llm.complete(_SYSTEM, user_prompt)
        verdict, reason = parse_continuity_verdict_line(raw)

        if verdict == "BREAK":
            return ContinuityDecision(
                ContinuityVerdict.close_and_new,
                reason=reason or "llm_break",
                layer="llm",
                confidence=0.75,
            )

        if verdict == "CONTINUE":
            return ContinuityDecision(
                ContinuityVerdict.continue_same,
                reason=reason or "llm_continue",
                layer="llm",
                confidence=0.75,
            )

        return ContinuityDecision(
            ContinuityVerdict.continue_same,
            reason="llm_unparsed_default_continue",
            layer="llm",
            confidence=0.5,
        )
