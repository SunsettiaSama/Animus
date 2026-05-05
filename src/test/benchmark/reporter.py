"""
Benchmark report writer.

Outputs:
  - JSON artifact  (machine-readable, consumed by drift.py and CI tools)
  - Markdown table (human-readable, written to $GITHUB_STEP_SUMMARY and a .md file)

CLI usage:
  python reporter.py benchmark-report.json            # print Markdown to stdout
  python reporter.py benchmark-report.json --md >> $GITHUB_STEP_SUMMARY
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from test.benchmark.metrics import ScenarioResult


def save_report(results: list[ScenarioResult], output_path: Path) -> None:
    records = []
    for r in results:
        d = asdict(r)
        records.append(d)
    output_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_report(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def to_markdown(results: list[ScenarioResult]) -> str:
    lines = [
        "## Benchmark Results",
        "",
        "| Scenario | Status | Steps | Tokens (P+C) | Wall ms | Retries | Quality |",
        "|----------|--------|-------|--------------|---------|---------|---------|",
    ]
    for r in results:
        total_tok = r.total_prompt_tokens + r.total_completion_tokens
        quality = f"{r.quality_score:.2f}" if r.quality_score is not None else "N/A"
        status_icon = "OK" if r.status == "done" else "FAIL"
        lines.append(
            f"| {r.scenario} "
            f"| {status_icon} "
            f"| {r.steps} "
            f"| {total_tok} ({r.total_prompt_tokens}+{r.total_completion_tokens}) "
            f"| {r.wall_ms:.0f} "
            f"| {r.llm_retries} "
            f"| {quality} |"
        )
    lines.append("")
    return "\n".join(lines)


def _main() -> None:
    import argparse
    import sys
    from pathlib import Path as _Path

    _src = _Path(__file__).resolve().parent.parent.parent
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

    parser = argparse.ArgumentParser(description="Print benchmark report as Markdown")
    parser.add_argument("report", nargs="?", help="Path to benchmark-report.json")
    parser.add_argument("--md", action="store_true", help="Output Markdown (default)")
    args = parser.parse_args()

    if not args.report:
        parser.print_help()
        sys.exit(0)

    from test.benchmark.metrics import (
        CallMetrics, ScenarioResult, ToolMetrics,
    )

    raw = load_report(Path(args.report))
    results: list[ScenarioResult] = []
    for d in raw:
        llm_calls = [CallMetrics(**c) for c in d.pop("llm_calls", [])]
        tool_calls = [ToolMetrics(**t) for t in d.pop("tool_calls", [])]
        results.append(ScenarioResult(**d, llm_calls=llm_calls, tool_calls=tool_calls))

    print(to_markdown(results))


if __name__ == "__main__":
    _main()
