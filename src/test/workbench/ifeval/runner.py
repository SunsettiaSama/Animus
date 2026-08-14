"""Worker/SubAgentRunner execution harness for the local IFEval sample."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from test.workbench.ifeval.dataset import IFEvalCase
from test.workbench.ifeval.report import (
    DEFAULT_OUTPUT_DIR,
    ResponseRecord,
    append_failure_record,
    append_response_record,
    load_response_records,
    score_and_write,
)


class CaseExecutor(Protocol):
    def execute(self, case: IFEvalCase) -> ResponseRecord: ...


class WorkerCaseExecutor:
    """Execute one text case through the production Worker runner."""

    def __init__(
        self,
        *,
        llm_cfg_path: str,
        max_steps: int = 6,
    ) -> None:
        self._llm_cfg_path = llm_cfg_path
        self._max_steps = max_steps

    def execute(self, case: IFEvalCase) -> ResponseRecord:
        from worker.profile import SubAgentConfig
        from worker.runner import SubAgentRunner

        base = SubAgentConfig().profiles["minimal"]
        profile = replace(
            base,
            max_steps=self._max_steps,
            tool_package=None,
            tools=[],
            system_note=(
                "完成下面的文字任务。最终答案必须严格遵循任务中的全部格式、"
                "长度、关键词与语言约束；不要调用工具。"
            ),
        )
        started = time.perf_counter()
        result = SubAgentRunner().run_sync(
            case.prompt,
            profile,
            self._llm_cfg_path,
        )
        wall_ms = (time.perf_counter() - started) * 1000
        return ResponseRecord(
            key=case.key,
            prompt=case.prompt,
            response=str(result.get("answer", "")),
            step_count=int(result.get("step_count", 0)),
            wall_ms=wall_ms,
        )


class FlowCaseExecutor:
    """Execute one text case through the real graph-topology FlowOrchestrator."""

    def __init__(
        self,
        *,
        llm_cfg_path: str,
        plan_dir: Path,
        max_steps: int = 6,
    ) -> None:
        self._llm_cfg_path = llm_cfg_path
        self._plan_dir = plan_dir
        self._max_steps = max_steps

    def _agent_config(self):
        from worker.profile import SubAgentConfig

        base = SubAgentConfig(llm_cfg_path=self._llm_cfg_path)
        profiles = {
            name: replace(
                profile,
                max_steps=min(profile.max_steps, self._max_steps),
                tool_package=None,
                tools=[],
                system_note=(
                    "完成分配的文字任务。输出必须严格保留原任务中的格式、"
                    "长度、关键词与语言约束；不要调用工具。"
                ),
            )
            for name, profile in base.profiles.items()
        }
        return replace(base, profiles=profiles, max_concurrent=2)

    async def _run(self, prompt: str):
        from agent.flow.base.budget import DecompositionBudget
        from worker.flow.cluster.config import (
            OrchestratorConfig,
            PlannerConfig,
            ReplannerConfig,
        )
        from worker.flow.cluster.orchestrator import FlowOrchestrator

        cfg = OrchestratorConfig(
            plan_dir=str(self._plan_dir),
            parallel_limit=2,
            human_edit=False,
            planner=PlannerConfig(
                mode="auto",
                tools=["scratchpad"],
                allow_search=False,
                max_steps=self._max_steps,
                max_retries=3,
                memory_short_term=True,
                memory_long_term=False,
                system_prompt_extra=(
                    "This benchmark is a text-only instruction-following task. "
                    "Create the smallest useful DAG and preserve every output "
                    "constraint verbatim in the final task description."
                ),
            ),
            replanner=ReplannerConfig(
                triggers=["on_task_failed", "on_module_complete"],
                max_cycles=1,
                result_summary_max_chars=2000,
            ),
            decomposition=DecompositionBudget(
                max_depth=0,
                max_width=4,
                max_atom_steps=self._max_steps,
                max_review_rounds=0,
            ),
        )
        orchestrator = FlowOrchestrator(
            cfg=cfg,
            llm_cfg_path=self._llm_cfg_path,
            agent_cfg=self._agent_config(),
        )
        return await orchestrator.run(prompt)

    @staticmethod
    def _answer_from_result(result) -> str:
        answer = str(result.answer or "").strip()
        if answer or result.doc is None:
            return answer
        done = [
            task
            for task in result.doc.all_tasks()
            if getattr(task, "result", "")
        ]
        return str(done[-1].result).strip() if done else ""

    @staticmethod
    def _step_count(result) -> int:
        if result.doc is None:
            return 0
        return sum(
            int(task.execution_ctx.step_count)
            for task in result.doc.all_tasks()
            if task.execution_ctx is not None
        )

    def execute(self, case: IFEvalCase) -> ResponseRecord:
        started = time.perf_counter()
        result = asyncio.run(self._run(case.prompt))
        wall_ms = (time.perf_counter() - started) * 1000
        if result.status == "failed":
            raise RuntimeError(
                f"Flow failed for IFEval key={case.key}: {result.error}"
            )
        return ResponseRecord(
            key=case.key,
            prompt=case.prompt,
            response=self._answer_from_result(result),
            step_count=self._step_count(result),
            wall_ms=wall_ms,
        )


def run_workbench(
    cases: list[IFEvalCase],
    executor: CaseExecutor,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit: int | None = None,
    resume: bool = True,
    workers: int = 1,
) -> dict:
    selected = cases[:limit] if limit is not None else list(cases)
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")

    responses_path = output_dir / "responses.jsonl"
    failures_path = output_dir / "failures.jsonl"
    existing = load_response_records(responses_path) if resume else []
    if not resume and responses_path.is_file():
        responses_path.unlink()
    records_by_key = {record.key: record for record in existing}

    pending: list[IFEvalCase] = []
    for case in selected:
        old = records_by_key.get(case.key)
        if old is not None:
            if old.prompt != case.prompt:
                raise ValueError(
                    f"resume prompt mismatch for IFEval key={case.key}"
                )
            continue
        pending.append(case)

    if workers == 1:
        completed = (
            (case, executor.execute(case))
            for case in pending
        )
        for case, record in completed:
            _commit_record(case, record, responses_path, records_by_key)
    else:
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="ifeval",
        ) as pool:
            future_cases = {
                pool.submit(executor.execute, case): case
                for case in pending
            }
            for future in as_completed(future_cases):
                case = future_cases[future]
                error = future.exception()
                if error is not None:
                    append_failure_record(
                        failures_path,
                        case=case,
                        error=error,
                    )
                    continue
                record = future.result()
                _commit_record(case, record, responses_path, records_by_key)

    selected_records = [
        records_by_key[case.key]
        for case in selected
        if case.key in records_by_key
    ]
    return score_and_write(
        selected,
        selected_records,
        output_dir=output_dir,
    )


def _commit_record(
    case: IFEvalCase,
    record: ResponseRecord,
    responses_path: Path,
    records_by_key: dict[int, ResponseRecord],
) -> None:
    if record.key != case.key or record.prompt != case.prompt:
        raise ValueError(
            f"executor returned mismatched case for key={case.key}"
        )
    append_response_record(responses_path, record)
    records_by_key[record.key] = record
