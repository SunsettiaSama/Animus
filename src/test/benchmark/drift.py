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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def _drift_alert(
    name: str,
    metric: str,
    current_val: float,
    past_vals: list[float],
    threshold: float,
) -> DriftAlert | None:
    """Return a DriftAlert if *current_val* drifts beyond *threshold* vs mean of *past_vals*."""
    if not past_vals:
        return None
    baseline = sum(past_vals) / len(past_vals)
    if baseline == 0:
        return None
    drift = (current_val - baseline) / baseline
    if abs(drift) <= threshold:
        return None
    return DriftAlert(
        scenario=name,
        metric=metric,
        current=current_val,
        baseline=baseline,
        drift_pct=drift * 100,
    )


def check_drift(
    current_results: list[dict],
    history: list[dict],
    threshold: float = 0.20,
    min_history_runs: int = 3,
    rolling_window: int = 10,
) -> list[DriftAlert]:
    """
    Compare current results against rolling average from history.

    Tracked metrics per scenario:
      total_tokens  — prompt + completion token count
      wall_ms       — end-to-end wall-clock time
      quality_score — 0-1 quality score (only when present in both current and history)
      retry_rate    — llm_retries / max(steps, 1) — parser degradation signal

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

        # ── total_tokens ──────────────────────────────────────────────────────
        current_tokens = (
            current["total_prompt_tokens"] + current["total_completion_tokens"]
        )
        past_tokens = [
            p["total_prompt_tokens"] + p["total_completion_tokens"] for p in window
        ]
        if a := _drift_alert(name, "total_tokens", float(current_tokens), past_tokens, threshold):
            alerts.append(a)

        # ── wall_ms ───────────────────────────────────────────────────────────
        if a := _drift_alert(
            name, "wall_ms",
            float(current["wall_ms"]),
            [p["wall_ms"] for p in window],
            threshold,
        ):
            alerts.append(a)

        # ── quality_score (skip when None in current or all-None in history) ──
        current_q = current.get("quality_score")
        if current_q is not None:
            past_q = [p["quality_score"] for p in window if p.get("quality_score") is not None]
            if a := _drift_alert(name, "quality_score", float(current_q), past_q, threshold):
                alerts.append(a)

        # ── retry_rate = llm_retries / max(steps, 1) ─────────────────────────
        current_retries = current.get("llm_retries", 0)
        current_steps = max(current.get("steps", 1), 1)
        current_rr = current_retries / current_steps
        past_rr = [
            p.get("llm_retries", 0) / max(p.get("steps", 1), 1)
            for p in window
        ]
        if a := _drift_alert(name, "retry_rate", current_rr, past_rr, threshold):
            alerts.append(a)

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
