"""Offline tests for the IFEval Worker workbench."""
from __future__ import annotations

import json
from pathlib import Path

from test.workbench.ifeval.dataset import (
    DEFAULT_CASES_PATH,
    DEFAULT_MANIFEST_PATH,
    IFEvalCase,
    load_cases,
    serialize_jsonl,
    sha256_text,
    stratified_sample,
)
from test.workbench.ifeval.evaluator import evaluate_case
from test.workbench.ifeval.report import ResponseRecord, load_response_records
from test.workbench.ifeval.runner import run_workbench


def _case(
    key: int,
    instruction_id: str,
    kwargs: dict | None = None,
) -> IFEvalCase:
    return IFEvalCase(
        key=key,
        prompt=f"prompt-{key}",
        instruction_id_list=(instruction_id,),
        kwargs=(kwargs or {},),
    )


def test_local_dataset_has_pinned_80_case_baseline():
    cases = load_cases()
    manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    text = DEFAULT_CASES_PATH.read_text(encoding="utf-8")

    assert len(cases) == 80
    assert len({case.key for case in cases}) == 80
    assert manifest["source_count"] == 541
    assert manifest["sample_count"] == 80
    assert manifest["license"] == "apache-2.0"
    assert manifest["sample_sha256"] == sha256_text(text)
    assert set(manifest["primary_family_counts"]) == {
        "change_case",
        "combination",
        "detectable_content",
        "detectable_format",
        "keywords",
        "language",
        "length_constraints",
        "punctuation",
        "startend",
    }


def test_stratified_sample_is_deterministic_and_balanced():
    source = [
        _case(i, f"{family}:rule")
        for i, family in enumerate(("alpha", "beta", "gamma") * 5)
    ]
    first = stratified_sample(source, sample_size=9)
    second = stratified_sample(reversed(source), sample_size=9)

    assert serialize_jsonl(first) == serialize_jsonl(second)
    counts: dict[str, int] = {}
    for item in first:
        counts[item.primary_family] = counts.get(item.primary_family, 0) + 1
    assert counts == {"alpha": 3, "beta": 3, "gamma": 3}


def test_official_verifier_strict_pass_and_fail():
    case = _case(1, "punctuation:no_comma")
    passed = evaluate_case(case, "This response contains no forbidden punctuation")
    failed = evaluate_case(case, "This response has a comma, so it fails")

    assert passed.strict_pass is True
    assert passed.loose_pass is True
    assert failed.strict_pass is False
    assert failed.loose_pass is False


def test_official_verifier_loose_can_remove_first_line():
    case = _case(
        2,
        "keywords:forbidden_words",
        {"forbidden_words": ["bad"]},
    )
    result = evaluate_case(case, "bad\nclean response")

    assert result.strict_pass is False
    assert result.loose_pass is True


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def execute(self, case: IFEvalCase) -> ResponseRecord:
        self.calls.append(case.key)
        response = (
            "clean response"
            if case.key == 10
            else "This answer includes alpha"
        )
        return ResponseRecord(
            key=case.key,
            prompt=case.prompt,
            response=response,
            step_count=1,
            wall_ms=float(case.key),
        )


class _PartlyFailingExecutor(_FakeExecutor):
    def execute(self, case: IFEvalCase) -> ResponseRecord:
        if case.key == 11:
            raise RuntimeError("planned test failure")
        return super().execute(case)


def test_runner_full_path_and_resume(tmp_path: Path):
    cases = [
        _case(10, "punctuation:no_comma"),
        _case(11, "keywords:existence", {"keywords": ["alpha"]}),
    ]
    executor = _FakeExecutor()
    summary = run_workbench(cases, executor, output_dir=tmp_path)

    assert executor.calls == [10, 11]
    assert summary["completed_count"] == 2
    assert summary["strict_prompt_accuracy"] == 1.0
    assert summary["strict_instruction_accuracy"] == 1.0
    assert (tmp_path / "responses.jsonl").is_file()
    assert (tmp_path / "results.jsonl").is_file()
    assert (tmp_path / "summary.json").is_file()

    resumed = _FakeExecutor()
    summary2 = run_workbench(
        cases,
        resumed,
        output_dir=tmp_path,
        resume=True,
    )
    assert resumed.calls == []
    assert summary2["strict_prompt_accuracy"] == 1.0
    assert len(load_response_records(tmp_path / "responses.jsonl")) == 2


def test_runner_parallel_execution_persists_all_records(tmp_path: Path):
    cases = [
        _case(10, "punctuation:no_comma"),
        _case(11, "keywords:existence", {"keywords": ["alpha"]}),
    ]
    executor = _FakeExecutor()

    summary = run_workbench(
        cases,
        executor,
        output_dir=tmp_path,
        workers=2,
    )

    assert set(executor.calls) == {10, 11}
    assert summary["completed_count"] == 2
    assert {
        record.key
        for record in load_response_records(tmp_path / "responses.jsonl")
    } == {10, 11}


def test_parallel_failure_is_recorded_without_stopping_batch(tmp_path: Path):
    cases = [
        _case(10, "punctuation:no_comma"),
        _case(11, "keywords:existence", {"keywords": ["alpha"]}),
    ]

    summary = run_workbench(
        cases,
        _PartlyFailingExecutor(),
        output_dir=tmp_path,
        workers=2,
    )

    assert summary["completed_count"] == 1
    assert summary["completion_rate"] == 0.5
    failure = json.loads(
        (tmp_path / "failures.jsonl").read_text(encoding="utf-8")
    )
    assert failure["key"] == 11
    assert failure["error_type"] == "RuntimeError"
