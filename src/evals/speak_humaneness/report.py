from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .persona_target import PersonaGroundTruth
from .runner_types import CaseRecord

COMPOSITE_WEIGHTS = {"portrait": 0.40, "turing": 0.35, "behavior": 0.25}

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = (
    _REPO_ROOT / ".react" / "benchmark" / "speak_humaneness" / "default"
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
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: JSONL row must be an object")
        rows.append(payload)
    return rows


def _mean_or_none(values: Iterable[float]) -> float | None:
    items = [value for value in values if value is not None and not math.isnan(value)]
    return round(mean(items), 4) if items else None


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * quantile))
    return ordered[rank - 1]


def _protocol_block(records: list[CaseRecord], key: str) -> dict[str, Any]:
    verdicts = [
        getattr(record, key) for record in records if record.ok and getattr(record, key)
    ]
    speak_values = [item.get("speak_identity") for item in verdicts]
    human = sum(value == "HUMAN" for value in speak_values)
    ai = sum(value == "AI" for value in speak_values)
    unknown = sum(value == "UNKNOWN" for value in speak_values)
    votes = [vote for item in verdicts for vote in item.get("votes", [])]
    valid_votes = [vote for vote in votes if vote.get("valid")]
    block: dict[str, Any] = {
        "judged_case_count": len(verdicts),
        "speak_human_count": human,
        "speak_ai_count": ai,
        "speak_unknown_count": unknown,
        "speak_human_rate": round(human / len(verdicts), 4) if verdicts else None,
        "repeat_unanimous_rate": round(
            sum(1 for item in verdicts if item.get("unanimous")) / len(verdicts), 4
        )
        if verdicts
        else None,
        "invalid_vote_count": sum(not vote.get("valid", False) for vote in votes),
        "valid_vote_count": len(valid_votes),
    }
    vote_human = sum(vote.get("speak_identity") == "HUMAN" for vote in valid_votes)
    block["vote_speak_human_rate"] = (
        round(vote_human / len(valid_votes), 4) if valid_votes else None
    )
    if key == "blind_both":
        block["user_ai_count"] = sum(
            item.get("user_identity") == "AI" for item in verdicts
        )
    return block


def _portrait_block(records: list[CaseRecord]) -> dict[str, Any]:
    matches = [
        record.match for record in records if record.ok and record.match is not None
    ]
    valid = [item for item in matches if item.get("parsed_ok")]
    dimension_detail: dict[str, dict[str, int]] = {}
    for item in valid:
        for dim in item.get("dimensions", []):
            detail = dimension_detail.setdefault(
                dim["name"], {"opportunity": 0, "captured": 0, "contradicted": 0}
            )
            if dim.get("opportunity"):
                detail["opportunity"] += 1
            if dim.get("opportunity") and dim.get("captured"):
                detail["captured"] += 1
            if dim.get("opportunity") and dim.get("contradicted"):
                detail["contradicted"] += 1
    return {
        "valid": len(valid),
        "invalid": len(matches) - len(valid),
        "recall_covered": _mean_or_none(
            [item["recall_covered"] for item in valid if item.get("recall_covered") is not None]
        ),
        "precision": _mean_or_none(
            [item["precision"] for item in valid if item.get("precision") is not None]
        ),
        "style_score_5": _mean_or_none(
            [item["style_score"] for item in valid if item.get("style_score") is not None]
        ),
        "contradiction_rate": _mean_or_none(
            [
                item["contradiction_rate"]
                for item in valid
                if item.get("contradiction_rate") is not None
            ]
        ),
        "fidelity": _mean_or_none(
            [item["fidelity"] for item in valid if item.get("fidelity") is not None]
        ),
        "dimension_detail": dimension_detail,
    }


def _behavior_block(records: list[CaseRecord]) -> dict[str, Any]:
    stats = [record.behavior for record in records if record.ok]
    if not stats:
        return {"naturalness": None}
    components = {
        key: _mean_or_none([item.get(key) for item in stats])
        for key in (
            "empty_rate",
            "robotic_marker_rate",
            "repeated_opener_rate",
            "echo_rate",
            "question_ratio",
            "mean_len",
            "len_std",
        )
    }
    return {
        "naturalness": _mean_or_none([item.get("naturalness") for item in stats]),
        "components": components,
        "flagged_cases": {
            flag: [
                record.case_id
                for record in records
                if record.ok and flag in record.behavior.get("flags", [])
            ]
            for flag in (
                "empty_reply",
                "robotic_markers",
                "repeated_opener",
                "echo",
                "interrogation",
                "never_asks",
            )
        },
    }


def summarize_responder(records: list[CaseRecord]) -> dict[str, Any]:
    ok = [record for record in records if record.ok]
    scored = [
        record.scores.get("humanness")
        for record in ok
        if record.scores.get("humanness") is not None
    ]
    latencies = [
        turn["wall_ms"]
        for record in ok
        for turn in record.transcript.get("turns", [])
    ]
    return {
        "completed": len(ok),
        "errors": len(records) - len(ok),
        "error_cases": [
            record.case_id for record in records if not record.ok
        ],
        "portrait": _portrait_block(records),
        "turing": {
            "known_user": _protocol_block(records, "known_user"),
            "blind_both": _protocol_block(records, "blind_both"),
        },
        "behavior": _behavior_block(records),
        "latency_ms": {
            "p50": round(_percentile(latencies, 0.50), 1),
            "p95": round(_percentile(latencies, 0.95), 1),
        },
        "async_fallback_count": sum(
            record.async_fallback_used for record in ok
        ),
        "char_silence_count": sum(
            1
            for record in ok
            for event in record.arm_events
            if event.get("kind") == "silence"
        ),
        "char_booking_count": sum(
            1
            for record in ok
            for event in record.arm_events
            if event.get("kind") == "booking"
        ),
        "humanness": _mean_or_none(scored),
    }


def build_summary(
    records: list[CaseRecord],
    *,
    ground_truth: PersonaGroundTruth,
    responders: tuple[str, ...],
    case_count: int,
) -> dict[str, Any]:
    by_responder: dict[str, list[CaseRecord]] = {
        responder: [] for responder in responders
    }
    for record in records:
        by_responder.setdefault(record.responder, []).append(record)

    responder_summaries = {
        responder: summarize_responder(items)
        for responder, items in by_responder.items()
        if items
    }

    # 逐 case 配对差值（同 case 跑过多条管线时）
    per_case: dict[str, dict[str, float]] = {}
    for record in records:
        if not record.ok or record.scores.get("humanness") is None:
            continue
        per_case.setdefault(record.case_id, {})[record.responder] = record.scores[
            "humanness"
        ]
    paired_cases = {
        case_id: values for case_id, values in per_case.items() if len(values) >= 2
    }
    deltas: dict[str, float | None] = {}
    names = sorted(responder_summaries)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            diffs = [
                values[left] - values[right]
                for case_id, values in paired_cases.items()
                if left in values and right in values
            ]
            deltas[f"{left} - {right}"] = _mean_or_none(diffs)

    by_tag: dict[str, dict[str, float | None]] = {}
    tag_groups: dict[str, dict[str, list[float]]] = {}
    for record in records:
        if not record.ok or record.scores.get("humanness") is None:
            continue
        for tag in record.tags:
            tag_groups.setdefault(tag, {}).setdefault(record.responder, []).append(
                record.scores["humanness"]
            )
    for tag, groups in sorted(tag_groups.items()):
        by_tag[tag] = {
            responder: _mean_or_none(values)
            for responder, values in groups.items()
        }

    return {
        "version": 1,
        "weights": dict(COMPOSITE_WEIGHTS),
        "score_formula": {
            "portrait_fidelity": "0.45*recall_covered + 0.35*precision + 0.20*(style_score/5)，缺项重归一",
            "humanness": "0.40*portrait_fidelity + 0.35*blind_both_human + 0.25*behavior_naturalness，缺项重归一",
        },
        "ground_truth": ground_truth.to_dict(),
        "case_count": case_count,
        "responders": responder_summaries,
        "paired": {
            "case_count": len(paired_cases),
            "mean_humanness_delta": deltas,
            "per_case": per_case,
        },
        "by_tag": by_tag,
    }


def write_summary(
    records: list[CaseRecord],
    *,
    ground_truth: PersonaGroundTruth,
    responders: tuple[str, ...],
    case_count: int,
    output_dir: Path,
) -> dict[str, Any]:
    summary = build_summary(
        records,
        ground_truth=ground_truth,
        responders=responders,
        case_count=case_count,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def render_report(summary: dict[str, Any], records: list[CaseRecord]) -> str:
    lines: list[str] = []
    lines.append("# speak 拟人度三维评测报告")
    lines.append("")
    gt = summary.get("ground_truth", {})
    lines.append(
        f"- 画像 ground truth：**{gt.get('name', '?')}**"
        f"（persona_revision={gt.get('source_revision', '?')}）"
    )
    lines.append(
        "- 维度：画像匹配（ portraits ）× 图灵盲测 × 行为统计；权重 "
        f"{summary.get('weights')}"
    )
    lines.append(f"- formula：{summary.get('score_formula')}")
    lines.append("")

    responders = summary.get("responders", {})
    lines.append("## 总览")
    lines.append("")
    header = (
        "| 管线 | 完成/报错 | 画像保真度 | 机会recall | precision | 风格/5"
        " | 图灵known人率 | 图灵blind人率 | 行为自然度 | 拟人度综合 |"
    )
    lines.append(header)
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, block in responders.items():
        portrait = block["portrait"]
        turing = block["turing"]
        behavior = block["behavior"]

        def pct(value: float | None) -> str:
            return "—" if value is None else f"{value * 100:.0f}%"

        def num(value: float | None, digits: int = 3) -> str:
            return "—" if value is None else f"{value:.{digits}f}"

        lines.append(
            f"| {name} | {block['completed']}/{block['errors']}"
            f" | {num(portrait['fidelity'])} | {num(portrait['recall_covered'])}"
            f" | {num(portrait['precision'])} | {num(portrait['style_score_5'], 1)}"
            f" | {pct(turing['known_user']['speak_human_rate'])}"
            f" | {pct(turing['blind_both']['speak_human_rate'])}"
            f" | {num(behavior.get('naturalness'))}"
            f" | **{num(block.get('humanness'))}** |"
        )
    lines.append("")

    paired = summary.get("paired", {})
    if paired.get("mean_humanness_delta"):
        lines.append("## 配对差值（同 case 逐对比较）")
        lines.append("")
        for name, delta in paired["mean_humanness_delta"].items():
            lines.append(f"- {name}: {delta if delta is None else round(delta, 4)}")
        lines.append("")

    lines.append("## 画像逐维捕捉（opportunity / captured / contradicted）")
    lines.append("")
    for name, block in responders.items():
        detail = block["portrait"].get("dimension_detail", {})
        if not detail:
            continue
        lines.append(f"**{name}**")
        lines.append("")
        lines.append("| 维度 | 触及 | 捕捉 | 矛盾 |")
        lines.append("|---|---|---|---|")
        for dim, counts in detail.items():
            lines.append(
                f"| {dim} | {counts['opportunity']} | {counts['captured']}"
                f" | {counts['contradicted']} |"
            )
        lines.append("")

    lines.append("## 行为指标成分")
    lines.append("")
    for name, block in responders.items():
        components = block["behavior"].get("components", {})
        if not components:
            continue
        rendered = "，".join(
            f"{key}={value}" for key, value in components.items() if value is not None
        )
        lines.append(f"- **{name}**：{rendered}")
    lines.append("")

    latency_lines = []
    for name, block in responders.items():
        latency = block.get("latency_ms", {})
        latency_lines.append(
            f"- **{name}**：p50={latency.get('p50')}ms，p95={latency.get('p95')}ms"
            f"，异步兜底 {block.get('async_fallback_count')} 次"
        )
    if latency_lines:
        lines.append("## 延迟与可靠性")
        lines.append("")
        lines.extend(latency_lines)
        lines.append("")

    example = _example_portrait(records)
    if example:
        lines.append("## 画像样例")
        lines.append("")
        lines.append(f"```json\n{example}\n```")
        lines.append("")
    return "\n".join(lines)


def _example_portrait(records: list[CaseRecord]) -> str | None:
    for record in records:
        if record.ok and record.extraction:
            return str(record.extraction.get("render", "")) or None
    return None


def write_report(
    summary: dict[str, Any],
    records: list[CaseRecord],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report.md"
    path.write_text(render_report(summary, records), encoding="utf-8")
    return path
