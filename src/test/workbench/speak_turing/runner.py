from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Iterable

from .dataset import SpeakTuringCase
from .judge import CategoricalDialogueJudge
from .report import (
    DEFAULT_OUTPUT_DIR,
    CaseResult,
    append_jsonl,
    load_jsonl,
    load_results,
    write_summary,
)
from .simulation import DialogueSimulator, DialogueTranscript


def _validate_completed_result(result: CaseResult) -> None:
    for verdict in (result.known_user, result.blind_both):
        if len(verdict.votes) != 3:
            raise ValueError(
                f"resume result {result.case_id!r} does not contain three "
                f"{verdict.protocol} votes"
            )


def _load_transcripts(path: Path) -> dict[str, DialogueTranscript]:
    transcripts = [
        DialogueTranscript.from_dict(payload)
        for payload in load_jsonl(path)
    ]
    indexed: dict[str, DialogueTranscript] = {}
    for transcript in transcripts:
        if transcript.case_id in indexed:
            raise ValueError(f"duplicate transcript case_id: {transcript.case_id}")
        indexed[transcript.case_id] = transcript
    return indexed


def _rewrite_judgments(path: Path, results: Iterable[CaseResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            for verdict in (result.known_user, result.blind_both):
                for vote in verdict.votes:
                    payload = {
                        "case_id": result.case_id,
                        **vote.to_dict(),
                    }
                    handle.write(
                        json.dumps(payload, ensure_ascii=False, sort_keys=True)
                        + "\n"
                    )


def _rewrite_results(path: Path, results: Iterable[CaseResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(
                json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
                + "\n"
            )


def run_workbench(
    cases: list[SpeakTuringCase],
    simulator: DialogueSimulator,
    judge: CategoricalDialogueJudge,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit: int | None = None,
    resume: bool = True,
    session_prefix: str = "speak-turing",
    on_progress: Callable[[], None] | None = None,
) -> dict:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    selected = cases[:limit] if limit is not None else list(cases)
    output_dir.mkdir(parents=True, exist_ok=True)
    transcripts_path = output_dir / "transcripts.jsonl"
    judgments_path = output_dir / "judgments.jsonl"
    results_path = output_dir / "results.jsonl"
    summary_path = output_dir / "summary.json"

    if not resume:
        for path in (
            transcripts_path,
            judgments_path,
            results_path,
            summary_path,
        ):
            if path.is_file():
                path.unlink()

    transcripts = _load_transcripts(transcripts_path) if resume else {}
    existing_results = load_results(results_path) if resume else []
    results_by_id = {result.case_id: result for result in existing_results}

    for case in selected:
        old_result = results_by_id.get(case.case_id)
        if old_result is not None:
            _validate_completed_result(old_result)
            if old_result.tags != case.tags:
                raise ValueError(f"resume metadata mismatch for {case.case_id}")
            continue

        transcript = transcripts.get(case.case_id)
        if transcript is None:
            transcript = simulator.run(
                case,
                session_id=f"{session_prefix}-{case.case_id}",
            )
            append_jsonl(transcripts_path, transcript.to_dict())
            transcripts[case.case_id] = transcript
        elif len(transcript.turns) != case.turns:
            raise ValueError(f"resume turn count mismatch for {case.case_id}")

        result = CaseResult(
            case_id=case.case_id,
            tags=case.tags,
            transcript=transcript,
            known_user=judge.judge_known_user(transcript),
            blind_both=judge.judge_blind_both(transcript),
        )
        append_jsonl(results_path, result.to_dict())
        results_by_id[case.case_id] = result

        ordered_partial = [
            results_by_id[item.case_id]
            for item in selected
            if item.case_id in results_by_id
        ]
        _rewrite_judgments(judgments_path, ordered_partial)
        write_summary(
            ordered_partial,
            sample_count=len(selected),
            output_dir=output_dir,
        )
        if on_progress is not None:
            on_progress()

    ordered = [
        results_by_id[case.case_id]
        for case in selected
        if case.case_id in results_by_id
    ]
    _rewrite_results(results_path, ordered)
    _rewrite_judgments(judgments_path, ordered)
    return write_summary(
        ordered,
        sample_count=len(selected),
        output_dir=output_dir,
    )
