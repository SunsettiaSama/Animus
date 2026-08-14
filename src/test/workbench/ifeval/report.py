"""Persistent response, case-result, and aggregate reports for IFEval."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from test.workbench.ifeval.dataset import IFEvalCase
from test.workbench.ifeval.evaluator import CaseEvaluation, evaluate_responses

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = (
    _REPO_ROOT / ".react" / "benchmark" / "workbench" / "ifeval"
)


@dataclass(frozen=True)
class ResponseRecord:
    key: int
    prompt: str
    response: str
    step_count: int
    wall_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "response": self.response,
            "step_count": self.step_count,
            "wall_ms": self.wall_ms,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ResponseRecord":
        return cls(
            key=int(raw["key"]),
            prompt=str(raw["prompt"]),
            response=str(raw["response"]),
            step_count=int(raw.get("step_count", 0)),
            wall_ms=float(raw.get("wall_ms", 0.0)),
        )


def load_response_records(path: Path) -> list[ResponseRecord]:
    if not path.is_file():
        return []
    records: list[ResponseRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"response record must be object: {path}")
            records.append(ResponseRecord.from_dict(payload))
    return records


def append_response_record(path: Path, record: ResponseRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
            + "\n"
        )
        handle.flush()


def append_failure_record(
    path: Path,
    *,
    case: IFEvalCase,
    error: BaseException,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "key": case.key,
        "prompt": case.prompt,
        "error_type": type(error).__name__,
        "error": str(error),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        )
        handle.flush()


def _ratio(correct: int, total: int) -> float:
    return correct / total if total else 0.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def build_summary(
    evaluations: Iterable[CaseEvaluation],
    records_by_key: dict[int, ResponseRecord],
    *,
    sample_count: int,
) -> dict[str, Any]:
    items = list(evaluations)
    strict_prompt_correct = sum(item.strict_pass for item in items)
    loose_prompt_correct = sum(item.loose_pass for item in items)
    strict_instruction_total = sum(len(item.strict_checks) for item in items)
    loose_instruction_total = sum(len(item.loose_checks) for item in items)
    strict_instruction_correct = sum(sum(item.strict_checks) for item in items)
    loose_instruction_correct = sum(sum(item.loose_checks) for item in items)

    family_counts: dict[str, dict[str, int]] = {}
    for item in items:
        for instruction_id, strict_ok, loose_ok in zip(
            item.instruction_ids,
            item.strict_checks,
            item.loose_checks,
        ):
            family = instruction_id.split(":", 1)[0]
            counts = family_counts.setdefault(
                family,
                {"total": 0, "strict_correct": 0, "loose_correct": 0},
            )
            counts["total"] += 1
            counts["strict_correct"] += int(strict_ok)
            counts["loose_correct"] += int(loose_ok)

    by_family = {
        family: {
            **counts,
            "strict_accuracy": _ratio(
                counts["strict_correct"],
                counts["total"],
            ),
            "loose_accuracy": _ratio(
                counts["loose_correct"],
                counts["total"],
            ),
        }
        for family, counts in sorted(family_counts.items())
    }

    completed_records = [
        records_by_key[item.key]
        for item in items
        if item.key in records_by_key
    ]
    latencies = [record.wall_ms for record in completed_records]
    steps = [record.step_count for record in completed_records]
    return {
        "sample_count": sample_count,
        "completed_count": len(items),
        "completion_rate": _ratio(len(items), sample_count),
        "strict_prompt_accuracy": _ratio(strict_prompt_correct, len(items)),
        "loose_prompt_accuracy": _ratio(loose_prompt_correct, len(items)),
        "strict_instruction_accuracy": _ratio(
            strict_instruction_correct,
            strict_instruction_total,
        ),
        "loose_instruction_accuracy": _ratio(
            loose_instruction_correct,
            loose_instruction_total,
        ),
        "strict_prompt_correct": strict_prompt_correct,
        "loose_prompt_correct": loose_prompt_correct,
        "instruction_count": strict_instruction_total,
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "average_steps": mean(steps) if steps else 0.0,
        "strict_failed_case_ids": [
            item.key for item in items if not item.strict_pass
        ],
        "by_instruction_family": by_family,
    }


def score_and_write(
    cases: list[IFEvalCase],
    records: list[ResponseRecord],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    records_by_key = {record.key: record for record in records}
    responses_by_key = {
        key: record.response for key, record in records_by_key.items()
    }
    evaluations = evaluate_responses(cases, responses_by_key)
    output_dir.mkdir(parents=True, exist_ok=True)

    results_path = output_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as handle:
        for evaluation in evaluations:
            payload = evaluation.to_dict()
            record = records_by_key[evaluation.key]
            payload["step_count"] = record.step_count
            payload["wall_ms"] = record.wall_ms
            handle.write(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            )

    summary = build_summary(
        evaluations,
        records_by_key,
        sample_count=len(cases),
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
