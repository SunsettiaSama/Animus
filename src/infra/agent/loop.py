"""最小 Tao loop：step() 为原语，run() 循环调用 step()。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from infra.agent.auditor import OutputAuditor
from infra.agent.parse import ParseResult, parse_tao_output
from infra.agent.ports import ActionRunner
from infra.agent.prompt import build_messages
from infra.agent.review import CallReview, CallReviewResult
from infra.agent.timeline import Timeline
from infra.agent.unit import ObservationUnit, ThoughtActionUnit, Unit, UserUnit
from infra.llm.llm import BaseLLM

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    done: bool
    answer: str = ""
    thought_action: ThoughtActionUnit | None = None
    observations: list[ObservationUnit] = field(default_factory=list)
    parse: ParseResult | None = None
    review: CallReviewResult | None = None
    step_index: int = -1


class BaseAgent:
    """infra 级可扩展 agent：Unit timeline + 最小 T/A/O 循环。"""

    def __init__(
        self,
        llm: BaseLLM,
        action_runner: ActionRunner,
        *,
        system: str = "",
        max_steps: int = 8,
        timeline: Timeline | None = None,
        call_review: CallReview | None = None,
        auditor: OutputAuditor | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        self._llm = llm
        self._action_runner = action_runner
        self._system = system
        self._max_steps = max_steps
        self._call_review = call_review
        self._auditor = auditor
        self.timeline = timeline if timeline is not None else Timeline()
        self._steps_taken = 0
        self._finished = False

    @property
    def system(self) -> str:
        return self._system

    def set_system(self, system: str) -> None:
        self._system = str(system or "")

    @property
    def steps_taken(self) -> int:
        return self._steps_taken

    @property
    def finished(self) -> bool:
        return self._finished

    def reset(self) -> None:
        self.timeline.clear()
        self._steps_taken = 0
        self._finished = False

    def inject(self, unit: Unit) -> Unit:
        return self.timeline.inject(unit)

    def add_user(self, text: str, **kwargs: Any) -> UserUnit:
        return self.timeline.add_user(text, **kwargs)

    def step(self) -> StepResult:
        if self._finished:
            raise RuntimeError("BaseAgent already finished; call reset() to start a new turn")
        if self._steps_taken >= self._max_steps:
            raise RuntimeError(f"BaseAgent max_steps exhausted ({self._max_steps})")

        step_index = self._steps_taken + 1
        snapped = self.timeline.snapshot()
        messages = build_messages(system=self._system, timeline=snapped)
        raw = self._llm.generate_messages(messages)
        parsed = parse_tao_output(raw)

        if not parsed.ok:
            obs = self.timeline.add_observation(
                f"parse error: {parsed.error}",
                tool="parse",
                step_index=step_index,
                source="parse",
            )
            self._steps_taken = step_index
            return StepResult(
                done=False,
                observations=[obs],
                parse=parsed,
                step_index=step_index,
            )

        ta = self.timeline.add_thought_action(
            thought=parsed.thought,
            action=parsed.action,
            action_input=parsed.action_input,
            calls=parsed.calls,
            output=parsed.output,
            step_index=step_index,
        )
        self._steps_taken = step_index
        self._submit_audit(snapped, raw, parsed, step_index)

        if parsed.is_finish:
            self._finished = True
            return StepResult(
                done=True,
                answer=parsed.answer,
                thought_action=ta,
                parse=parsed,
                step_index=step_index,
            )

        review = self._review_calls(parsed.calls)
        if review is not None and not review.ok:
            obs = self.timeline.add_observation(
                review.correction,
                tool="review",
                step_index=step_index,
                source="review",
            )
            return StepResult(
                done=False,
                observations=[obs],
                parse=parsed,
                review=review,
                step_index=step_index,
            )

        results = self._action_runner.run(list(parsed.calls))
        observations: list[ObservationUnit] = []
        for item in results:
            tool = str(item.get("tool") or item.get("action") or "").strip()
            observation = str(item.get("observation") or "")
            obs = self.timeline.add_observation(
                observation,
                parent_id=ta.unit_id,
                tool=tool,
                step_index=step_index,
                source="tool",
            )
            observations.append(obs)

        return StepResult(
            done=False,
            thought_action=ta,
            observations=observations,
            parse=parsed,
            review=review,
            step_index=step_index,
        )

    def _review_calls(self, calls: list[dict]) -> CallReviewResult | None:
        if self._call_review is None:
            return None
        try:
            return self._call_review.review(list(calls))
        except Exception:
            # 审查器自身故障不阻塞主循环：放行并记录（fail-open）。
            logger.warning("call_review raised; passing calls through", exc_info=True)
            return CallReviewResult(ok=True)

    def _submit_audit(
        self, snapped: Timeline, raw: str, parsed: ParseResult, step_index: int
    ) -> None:
        auditor = self._auditor
        if auditor is None or not auditor.enabled:
            return
        if not (parsed.is_finish or auditor.cfg.scope == "every_step"):
            return
        auditor.submit(
            context=snapped.render(),
            output=raw,
            step_index=step_index,
            scope="finish" if parsed.is_finish else "step",
        )

    def run(self, question: str) -> str:
        self.add_user(question)
        while True:
            result = self.step()
            if result.done:
                return result.answer
            if self._steps_taken >= self._max_steps:
                raise RuntimeError(f"BaseAgent max_steps exhausted ({self._max_steps})")
