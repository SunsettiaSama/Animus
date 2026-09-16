from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .behavior import behavior_stats
from .persona_target import PersonaGroundTruth
from .portrait import extract_portrait, match_portrait
from .report import append_jsonl, load_jsonl, write_summary
from .runner_types import CaseRecord, humanness_score
from .runtime import EvalRuntime
from .simulation_compat import DialogueTranscript, SpeakTuringCase

logger = logging.getLogger("evals.speak_humaneness")

CASE_VERSION = 1


def run_eval(
    cases: list[SpeakTuringCase],
    runtime: EvalRuntime,
    ground_truth: PersonaGroundTruth,
    *,
    responders: tuple[str, ...],
    output_dir: Path,
    limit: int | None = None,
    case_ids: tuple[str, ...] = (),
    resume: bool = True,
    session_prefix: str = "speak-humaneness",
    on_progress: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if case_ids:
        wanted = set(case_ids)
        missing = wanted - {case.case_id for case in cases}
        if missing:
            raise ValueError(f"case_ids not in dataset: {sorted(missing)}")
        selected = [case for case in cases if case.case_id in wanted]
    else:
        selected = list(cases)
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("no cases selected")

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw_llm.jsonl"
    records_path = output_dir / "records.jsonl"

    existing: dict[tuple[str, str], CaseRecord] = {}
    if resume and records_path.is_file():
        for row in load_jsonl(records_path):
            record = CaseRecord.from_dict(row)
            existing[(record.responder, record.case_id)] = record

    completed: list[CaseRecord] = []
    for case in selected:
        for responder in responders:
            key = (responder, case.case_id)
            previous = existing.get(key)
            if previous is not None and previous.ok:
                completed.append(previous)
                continue
            simulator = runtime.simulators.get(responder)
            if simulator is None:
                raise ValueError(f"no simulator wired for responder {responder!r}")
            started = time.perf_counter()
            record = _evaluate_case(
                case,
                responder,
                simulator,
                runtime,
                ground_truth,
                session_id=f"{session_prefix}-{responder}-{case.case_id}",
                raw_path=raw_path,
            )
            record.wall_ms_total = round((time.perf_counter() - started) * 1000, 1)
            record.created_at = datetime.now(timezone.utc).isoformat()
            append_jsonl(records_path, record.to_dict())
            completed.append(record)
            scores = record.scores
            logger.info(
                "case=%s responder=%s ok=%s humanness=%s portrait=%s blind=%s behavior=%s (+%.1fs)",
                case.case_id,
                responder,
                record.ok,
                scores.get("humanness"),
                scores.get("portrait_fidelity"),
                scores.get("blind_human"),
                scores.get("behavior_naturalness"),
                record.wall_ms_total / 1000.0,
            )
            write_summary(
                completed,
                ground_truth=ground_truth,
                responders=responders,
                case_count=len(selected),
                output_dir=output_dir,
            )
            if on_progress is not None:
                on_progress()

    # 最终汇总覆盖目录内全部臂：records.jsonl 是聚合单元，多臂共用一个目录时
    # 只汇总本次 invocation 会把其它臂的结果覆盖掉。
    ordered = [CaseRecord.from_dict(row) for row in load_jsonl(records_path)]
    present = sorted({record.responder for record in ordered})
    summary = write_summary(
        ordered,
        ground_truth=ground_truth,
        responders=tuple(present),
        case_count=len(selected),
        output_dir=output_dir,
    )
    return summary


def _evaluate_case(
    case: SpeakTuringCase,
    responder: str,
    simulator: Any,
    runtime: EvalRuntime,
    ground_truth: PersonaGroundTruth,
    *,
    session_id: str,
    raw_path: Path,
) -> CaseRecord:
    try:
        transcript = simulator.run(case, session_id=session_id)
    except Exception as exc:  # noqa: BLE001 - 单 case 失败不应拖垮整场评测
        logger.warning("simulate failed case=%s responder=%s: %s", case.case_id, responder, exc)
        return CaseRecord(
            case_id=case.case_id,
            responder=responder,
            tags=case.tags,
            ok=False,
            transcript={},
            behavior={},
            error=f"simulate: {exc}",
        )

    port = runtime.extras.get("ports", {}).get(responder)
    fallback_before = getattr(port, "consumed_fallback_count", 0) if port else 0

    def log_raw(stage: str, payload: dict[str, Any]) -> None:
        append_jsonl(
            raw_path,
            {"stage": stage, "case_id": case.case_id, "responder": responder, **payload},
        )

    known_user = None
    blind_both = None
    try:
        known_user = runtime.judge.judge_known_user(transcript).to_dict()
        blind_both = runtime.judge.judge_blind_both(transcript).to_dict()
    except Exception as exc:  # noqa: BLE001
        logger.warning("turing judge failed case=%s responder=%s: %s", case.case_id, responder, exc)

    extraction = None
    match = None
    try:
        extraction = extract_portrait(
            runtime.judge_llm,
            transcript,
            log_raw=log_raw,
            case_id=case.case_id,
            responder=responder,
        )
        match = match_portrait(
            runtime.judge_llm,
            extraction,
            transcript,
            ground_truth,
            log_raw=log_raw,
            case_id=case.case_id,
            responder=responder,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("portrait failed case=%s responder=%s: %s", case.case_id, responder, exc)

    behavior = behavior_stats(transcript)
    scores = _score(match, blind_both, behavior)

    arm_events = list(getattr(port, "events", []) or []) if port is not None else []
    if port is not None and hasattr(port, "events"):
        port.events = []

    return CaseRecord(
        case_id=case.case_id,
        responder=responder,
        tags=case.tags,
        ok=True,
        transcript=transcript.to_dict(),
        behavior=behavior.to_dict(),
        scores=scores,
        known_user=known_user,
        blind_both=blind_both,
        extraction=extraction.to_dict() if extraction is not None else None,
        match=match.to_dict() if match is not None else None,
        async_fallback_used=max(
            0, getattr(port, "consumed_fallback_count", 0) - fallback_before
        )
        if port
        else 0,
        arm_events=arm_events,
    )


def _score(match: Any, blind_both: dict[str, Any] | None, behavior: Any) -> dict[str, Any]:
    portrait_fidelity = None
    if match is not None:
        portrait_fidelity = match.fidelity
    blind_human = None
    if blind_both is not None and blind_both.get("speak_identity") in {"HUMAN", "AI"}:
        blind_human = 1.0 if blind_both["speak_identity"] == "HUMAN" else 0.0
    naturalness = behavior.naturalness if behavior.turns else None
    humanness = humanness_score(
        portrait_fidelity=portrait_fidelity,
        blind_human=blind_human,
        behavior_naturalness=naturalness,
    )
    return {
        "portrait_fidelity": portrait_fidelity,
        "blind_human": blind_human,
        "behavior_naturalness": naturalness,
        "humanness": humanness,
    }
