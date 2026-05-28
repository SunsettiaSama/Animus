from __future__ import annotations

from typing import TYPE_CHECKING

from .parse import parse_turing_verdict_line
from .protocols import ExternalAgentJudgeHandler
from .types import TuringTranscript, TuringVerdict, TuringVerdictKind

if TYPE_CHECKING:
    from infra.llm import BaseLLM

_TURING_JUDGE_SYSTEM = """你是「主体性裁决器」，执行伪图灵测试：只根据对话转录判断受测方是否像一个 agent（有稳定人格、第一人称主观体验、内在思考与外在表达区分、跨轮连贯），而不是模板客服或纯信息检索机。

只输出两行：
第一行：AGENT 或 NOT_AGENT（必须大写英文之一）
第二行：reason: 简短中文理由

判为 AGENT 的典型信号：
- 第一人称、具身或情境化表达；think 与 speak/action 有分工
- 跨轮记住用户话题或自称记忆/经历；非机械 FAQ
- 有情绪、犹豫、主动延伸，而非仅回答问题

判为 NOT_AGENT 的典型信号：
- 纯模板客服、百科式罗列、无主观立场
- 每轮割裂、无连续性；只有工具输出痕迹
- 明确标注为对照组模板客服

转录中标注【对照组】时，除非出现强烈反证，默认 NOT_AGENT。"""


class TuringAgentJudge:
    """外部 agent 接口：对 Soul 采集的 transcript 做 agent / not-agent 裁决。"""

    def __init__(self, handler: ExternalAgentJudgeHandler) -> None:
        self._handler = handler

    def judge(self, transcript: TuringTranscript) -> TuringVerdict:
        user_prompt = transcript.render_for_judge()
        raw = self._handler.complete(_TURING_JUDGE_SYSTEM, user_prompt)
        head, reason = parse_turing_verdict_line(raw)
        if head == "AGENT":
            return TuringVerdict(
                kind=TuringVerdictKind.agent,
                reason=reason or "external_agent_agent",
                layer="external",
            )
        if head == "NOT_AGENT":
            return TuringVerdict(
                kind=TuringVerdictKind.not_agent,
                reason=reason or "external_agent_not_agent",
                layer="external",
            )
        return TuringVerdict(
            kind=TuringVerdictKind.unknown,
            reason=reason or "external_agent_unparsed",
            layer="external",
        )


class InfraTuringJudgeHandler:
    """``infra.llm.BaseLLM`` → :class:`ExternalAgentJudgeHandler`。"""

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def complete(self, system: str, user: str) -> str:
        from infra.llm import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user),
        ]
        return self._llm.generate_messages(messages).strip()
