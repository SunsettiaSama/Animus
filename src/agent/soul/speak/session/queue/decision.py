from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent.soul.workers import DomainWorker

from ...io.outbound.stream.protocol.tags import speak_tag
from ...io.outbound.stream.parse.tags import iter_tag_blocks
from ...llm.engine import SpeakLLMEngine
from .types import InterruptContext


@dataclass
class QueueDecisionResult:
    maintain: bool = False
    thought: str = ""
    raw: str = ""
    reorder: tuple[int, ...] | None = None


QueueDecisionHandler = Callable[[str, int, QueueDecisionResult], None]

_REORDER_PATTERN = re.compile(
    r"(?:顺序|重排|order)[：:\s]+([0-9,\s、]+)",
    re.IGNORECASE,
)


def parse_queue_reorder(thought: str, *, count: int) -> tuple[int, ...] | None:
    if count <= 1 or not thought.strip():
        return None
    match = _REORDER_PATTERN.search(thought)
    if match is None:
        return None
    indices: list[int] = []
    seen: set[int] = set()
    for piece in re.findall(r"\d+", match.group(1)):
        index = int(piece)
        if index < 1 or index > count or index in seen:
            continue
        indices.append(index)
        seen.add(index)
    if not indices:
        return None
    for index in range(1, count + 1):
        if index not in seen:
            indices.append(index)
    return tuple(indices)


def render_queue_decision_system() -> str:
    think = speak_tag("think")
    keep = speak_tag("state", "keep_queue")
    drop = speak_tag("state", "drop_queue")
    lines = [
        "【队列决策】（仅内部决策，不对用户展示）",
        "",
        "背景：用户在 agent 尚未完成 outward 推送时插话，compose 推送队列已被挂起。",
        "任务：仅依据下方快照，独立判断挂起项是否仍应继续执行。",
        "",
        "决策要点：",
        "- 用户最新输入优先，评估挂起项是否仍相关",
        "- 若维持队列，在 think 中说明恢复后的执行顺序；需重排时写明「顺序：2,1,3」（编号对应快照序号）",
        "",
        "输出要求：",
        f"- 必须写 {think}：维持/丢弃理由；若维持，写明顺序或重排方案（格式：顺序：1,2,3）",
        f"- 必须写 {keep} 或 {drop} 之一",
        "- 不要写 speak、action、recall、share 等对用户可见内容",
    ]
    return "\n".join(lines)


def render_queue_decision_user(ctx: InterruptContext) -> str:
    lines = [
        "请对以下挂起 compose 队列做维持/丢弃决策。",
    ]
    if ctx.suspended_compose_count > 0:
        lines.append(f"挂起队列项数：{ctx.suspended_compose_count}")
    if ctx.suspended_compose_summary.strip():
        lines.append(f"队列快照：{ctx.suspended_compose_summary.strip()}")
    if ctx.dialogue_compressed.strip():
        lines.append(
            "会话蒸馏摘要（仅供决策，不含 persona/presence/status）：\n"
            f"{ctx.dialogue_compressed.strip()}",
        )
    if ctx.partial_agent_output.strip():
        lines.append(f"尚未完成推送的 agent 输出片段：{ctx.partial_agent_output.strip()}")
    if ctx.previous_user_text.strip():
        lines.append(f"被打断的上一轮用户输入：{ctx.previous_user_text.strip()}")
    lines.append(f"用户最新输入（优先）：{ctx.new_user_text.strip()}")
    return "\n".join(lines)


def parse_queue_decision(raw: str) -> QueueDecisionResult:
    thinks: list[str] = []
    maintain = False
    has_state = False
    for block in iter_tag_blocks(raw):
        if block.kind == "think" and block.content:
            thinks.append(block.content)
        elif block.kind == "state" and block.content:
            has_state = True
            state = block.content.strip().lower()
            if state in ("keep_queue", "keep"):
                maintain = True
            elif state in ("drop_queue", "drop"):
                maintain = False
    if not has_state and thinks:
        lowered = "\n".join(thinks).lower()
        if "维持" in lowered or "继续" in lowered or "keep" in lowered:
            maintain = True
    return QueueDecisionResult(
        maintain=maintain,
        thought="\n".join(thinks),
        raw=raw,
    )


def finalize_queue_decision(
    result: QueueDecisionResult,
    *,
    suspended_count: int,
) -> QueueDecisionResult:
    if not result.maintain or suspended_count <= 1:
        return QueueDecisionResult(
            maintain=result.maintain,
            thought=result.thought,
            raw=result.raw,
            reorder=None,
        )
    reorder = parse_queue_reorder(result.thought, count=suspended_count)
    return QueueDecisionResult(
        maintain=result.maintain,
        thought=result.thought,
        raw=result.raw,
        reorder=reorder,
    )


class QueueDecisionRunner:
    """异步队列决策：插队时独立 LLM 轮，不阻塞当前 outward 推送。"""

    def __init__(
        self,
        *,
        worker: DomainWorker | None = None,
        llm: SpeakLLMEngine | None = None,
    ) -> None:
        self._worker = worker or DomainWorker("speak-queue-decision-worker")
        self._llm = llm
        self._on_complete: QueueDecisionHandler | None = None

    @property
    def worker(self) -> DomainWorker:
        return self._worker

    def set_llm(self, llm: SpeakLLMEngine | None) -> None:
        self._llm = llm

    def set_complete_handler(self, handler: QueueDecisionHandler | None) -> None:
        self._on_complete = handler

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()

    def schedule(
        self,
        session_id: str,
        ctx: InterruptContext,
        token: int,
        llm: SpeakLLMEngine | None = None,
    ) -> None:
        engine = llm or self._llm
        if ctx.suspended_compose_count <= 0:
            self._emit(
                session_id,
                token,
                QueueDecisionResult(maintain=False, thought="empty suspended queue"),
            )
            return
        if engine is None or engine.llm is None:
            self._emit(
                session_id,
                token,
                QueueDecisionResult(maintain=False, thought="llm unavailable"),
            )
            return
        if self._worker.status()["state"] != "running":
            self._emit(
                session_id,
                token,
                QueueDecisionResult(maintain=False, thought="decision worker stopped"),
            )
            return

        def _job() -> None:
            system = render_queue_decision_system()
            user = render_queue_decision_user(ctx)
            raw = engine.generate(user, system=system).text
            parsed = parse_queue_decision(raw)
            result = finalize_queue_decision(
                parsed,
                suspended_count=ctx.suspended_compose_count,
            )
            self._emit(session_id, token, result)

        self._worker.enqueue(_job)

    def _emit(self, session_id: str, token: int, result: QueueDecisionResult) -> None:
        handler = self._on_complete
        if handler is not None:
            handler(session_id, token, result)
