"""
Baseline drift detector.

Compares the current benchmark run against historical results stored in
history.json.  Emits DriftAlert objects when a metric drifts more than
``threshold`` (default 20 %) from the rolling average of the last N runs.

CLI usage (called by nightly.yml after pytest):
  python drift.py benchmark-report.json history.json [--threshold 0.20]

Exit codes:
  0  no drift detected (or insufficient history)
  1  drift detected (alerts are printed to stderr and stdout)
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class DriftAlert:
    scenario: str
    metric: str
    current: float
    baseline: float
    drift_pct: float

    def __str__(self) -> str:
        direction = "▲" if self.drift_pct > 0 else "▼"
        return (
            f"[DRIFT] {self.scenario} / {self.metric}: "
            f"{self.current:.1f} vs baseline {self.baseline:.1f} "
            f"({direction}{abs(self.drift_pct):.1f}%)"
        )


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def append_history(
    path: Path,
    results: list[dict],
    run_at: str | None = None,
    max_runs: int = 50,
) -> None:
    history = load_history(path)
    history.append(
        {
            "run_at": run_at or datetime.now(timezone.utc).isoformat(),
            "results": results,
        }
    )
    history = history[-max_runs:]
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def check_drift(
    current_results: list[dict],
    history: list[dict],
    threshold: float = 0.20,
    min_history_runs: int = 3,
    rolling_window: int = 10,
) -> list[DriftAlert]:
    """
    Compare current results against rolling average from history.

    Returns a list of DriftAlert, empty when no drift exceeds threshold.
    """
    by_scenario: dict[str, list[dict]] = {}
    for run in history:
        for r in run.get("results", []):
            by_scenario.setdefault(r["scenario"], []).append(r)

    alerts: list[DriftAlert] = []
    for current in current_results:
        name = current["scenario"]
        past = by_scenario.get(name, [])
        if len(past) < min_history_runs:
            continue

        window = past[-rolling_window:]

        current_tokens = (
            current["total_prompt_tokens"] + current["total_completion_tokens"]
        )
        past_tokens = [
            p["total_prompt_tokens"] + p["total_completion_tokens"] for p in window
        ]
        avg_tokens = sum(past_tokens) / len(past_tokens)
        if avg_tokens > 0:
            drift = (current_tokens - avg_tokens) / avg_tokens
            if abs(drift) > threshold:
                alerts.append(
                    DriftAlert(
                        scenario=name,
                        metric="total_tokens",
                        current=float(current_tokens),
                        baseline=avg_tokens,
                        drift_pct=drift * 100,
                    )
                )

        past_wall = [p["wall_ms"] for p in window]
        avg_wall = sum(past_wall) / len(past_wall)
        if avg_wall > 0:
            drift = (current["wall_ms"] - avg_wall) / avg_wall
            if abs(drift) > threshold:
                alerts.append(
                    DriftAlert(
                        scenario=name,
                        metric="wall_ms",
                        current=float(current["wall_ms"]),
                        baseline=avg_wall,
                        drift_pct=drift * 100,
                    )
                )

    return alerts


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Detect benchmark metric drift")
    parser.add_argument("report", help="benchmark report JSON path")
    parser.add_argument(
        "history",
        nargs="?",
        default=".react/benchmark/history.json",
        help="history.json path (created if absent, default: .react/benchmark/history.json)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.20,
        help="Drift fraction that triggers an alert (default: 0.20 = 20%%)",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=3,
        help="Minimum history runs required before checking drift (default: 3)",
    )
    args = parser.parse_args()

    report_path = Path(args.report)
    history_path = Path(args.history)

    current = json.loads(report_path.read_text(encoding="utf-8"))
    history = load_history(history_path)

    alerts = check_drift(
        current,
        history,
        threshold=args.threshold,
        min_history_runs=args.min_runs,
    )

    append_history(history_path, current)

    if alerts:
        print(f"\n{'─' * 60}")
        print(f"  {len(alerts)} DRIFT ALERT(S) DETECTED")
        print(f"{'─' * 60}")
        for a in alerts:
            print(str(a))
        print(f"{'─' * 60}\n")
        sys.exit(1)
    else:
        print("No drift detected.")
        sys.exit(0)


if __name__ == "__main__":
    _main()
