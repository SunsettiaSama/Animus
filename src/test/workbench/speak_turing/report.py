from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .judge import ProtocolVerdict
from .simulation import DialogueTranscript

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = (
    _REPO_ROOT
    / ".react"
    / "benchmark"
    / "workbench"
    / "speak_turing"
    / "default"
)


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    tags: tuple[str, ...]
    transcript: DialogueTranscript
    known_user: ProtocolVerdict
    blind_both: ProtocolVerdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "tags": list(self.tags),
            "transcript": self.transcript.to_dict(),
            "known_user": self.known_user.to_dict(),
            "blind_both": self.blind_both.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CaseResult":
        return cls(
            case_id=str(raw["case_id"]),
            tags=tuple(str(item) for item in raw.get("tags", [])),
            transcript=DialogueTranscript.from_dict(raw["transcript"]),
            known_user=ProtocolVerdict.from_dict(raw["known_user"]),
            blind_both=ProtocolVerdict.from_dict(raw["blind_both"]),
        )


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: JSONL row must be an object")
        rows.append(payload)
    return rows


def load_results(path: Path) -> list[CaseResult]:
    return [CaseResult.from_dict(row) for row in load_jsonl(path)]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * quantile))
    return ordered[rank - 1]


def _protocol_counts(
    results: list[CaseResult],
    *,
    protocol: str,
) -> dict[str, Any]:
    verdicts = [
        result.known_user if protocol == "known_user" else result.blind_both
        for result in results
    ]
    speak_ai = sum(item.speak_identity == "AI" for item in verdicts)
    speak_human = sum(item.speak_identity == "HUMAN" for item in verdicts)
    speak_unknown = sum(item.speak_identity == "UNKNOWN" for item in verdicts)
    valid_votes = [
        vote
        for item in verdicts
        for vote in item.votes
        if vote.valid
    ]
    vote_speak_ai = sum(
        vote.speak_identity == "AI"
        for vote in valid_votes
    )
    vote_speak_human = sum(
        vote.speak_identity == "HUMAN"
        for vote in valid_votes
    )
    invalid_votes = sum(
        sum(not vote.valid for vote in item.votes)
        for item in verdicts
    )
    payload: dict[str, Any] = {
        "case_count": len(verdicts),
        "speak_ai_count": speak_ai,
        "speak_human_count": speak_human,
        "speak_unknown_count": speak_unknown,
        "speak_ai_detection_accuracy": _ratio(speak_ai, len(verdicts)),
        "speak_human_likeness_rate": _ratio(speak_human, len(verdicts)),
        "valid_speak_vote_count": len(valid_votes),
        "vote_speak_ai_count": vote_speak_ai,
        "vote_speak_human_count": vote_speak_human,
        "vote_speak_ai_detection_accuracy": _ratio(
            vote_speak_ai,
            len(valid_votes),
        ),
        "vote_speak_human_likeness_rate": _ratio(
            vote_speak_human,
            len(valid_votes),
        ),
        "repeat_unanimous_rate": _ratio(
            sum(item.unanimous for item in verdicts),
            len(verdicts),
        ),
        "invalid_vote_count": invalid_votes,
    }
    if protocol == "blind_both":
        user_ai = sum(item.user_identity == "AI" for item in verdicts)
        vote_user_ai = sum(
            vote.user_identity == "AI"
            for vote in valid_votes
        )
        exact = sum(
            item.user_identity == "AI" and item.speak_identity == "AI"
            for item in verdicts
        )
        payload.update(
            {
                "user_ai_count": user_ai,
                "user_ai_detection_accuracy": _ratio(user_ai, len(verdicts)),
                "vote_user_ai_count": vote_user_ai,
                "vote_user_ai_detection_accuracy": _ratio(
                    vote_user_ai,
                    len(valid_votes),
                ),
                "exact_pair_accuracy": _ratio(exact, len(verdicts)),
            }
        )
    return payload


def _by_tag(results: list[CaseResult]) -> dict[str, Any]:
    groups: dict[str, list[CaseResult]] = {}
    for result in results:
        for tag in result.tags:
            groups.setdefault(tag, []).append(result)
    return {
        tag: {
            "case_count": len(items),
            "known_user_speak_human_rate": _ratio(
                sum(item.known_user.speak_identity == "HUMAN" for item in items),
                len(items),
            ),
            "blind_both_speak_human_rate": _ratio(
                sum(item.blind_both.speak_identity == "HUMAN" for item in items),
                len(items),
            ),
            "protocol_agreement_rate": _ratio(
                sum(
                    item.known_user.speak_identity
                    == item.blind_both.speak_identity
                    for item in items
                ),
                len(items),
            ),
        }
        for tag, items in sorted(groups.items())
    }


def build_summary(
    results: Iterable[CaseResult],
    *,
    sample_count: int,
) -> dict[str, Any]:
    items = list(results)
    latencies = [
        turn.wall_ms
        for item in items
        for turn in item.transcript.turns
    ]
    comparable = [
        item
        for item in items
        if item.known_user.speak_identity != "UNKNOWN"
        and item.blind_both.speak_identity != "UNKNOWN"
    ]
    agree = sum(
        item.known_user.speak_identity == item.blind_both.speak_identity
        for item in comparable
    )
    positions: dict[str, list[CaseResult]] = {"A": [], "B": []}
    for item in items:
        positions.setdefault(item.blind_both.speak_position, []).append(item)
    position_breakdown = {
        position: {
            "case_count": len(group),
            "speak_human_rate": _ratio(
                sum(item.blind_both.speak_identity == "HUMAN" for item in group),
                len(group),
            ),
        }
        for position, group in positions.items()
        if group
    }
    return {
        "sample_count": sample_count,
        "completed_count": len(items),
        "completion_rate": _ratio(len(items), sample_count),
        "ground_truth": {"user_simulator": "AI", "speak": "AI"},
        "known_user": _protocol_counts(items, protocol="known_user"),
        "blind_both": _protocol_counts(items, protocol="blind_both"),
        "protocol_comparison": {
            "comparable_case_count": len(comparable),
            "speak_identity_agreement_rate": _ratio(agree, len(comparable)),
            "blind_position_breakdown": position_breakdown,
        },
        "dialogue": {
            "turn_count": sum(len(item.transcript.turns) for item in items),
            "empty_response_count": sum(
                not turn.speak.strip()
                for item in items
                for turn in item.transcript.turns
            ),
            "cases_with_empty_response": [
                item.case_id
                for item in items
                if any(not turn.speak.strip() for turn in item.transcript.turns)
            ],
            "average_turns_per_case": mean(
                [len(item.transcript.turns) for item in items]
            )
            if items
            else 0.0,
            "speak_latency_p50_ms": _percentile(latencies, 0.50),
            "speak_latency_p95_ms": _percentile(latencies, 0.95),
        },
        "by_tag": _by_tag(items),
        "known_user_human_case_ids": [
            item.case_id
            for item in items
            if item.known_user.speak_identity == "HUMAN"
        ],
        "blind_both_human_case_ids": [
            item.case_id
            for item in items
            if item.blind_both.speak_identity == "HUMAN"
        ],
    }


def write_summary(
    results: list[CaseResult],
    *,
    sample_count: int,
    output_dir: Path,
) -> dict[str, Any]:
    summary = build_summary(results, sample_count=sample_count)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
