from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from test.benchmark.protocol import BenchmarkReport, BenchmarkRunner

if TYPE_CHECKING:
    from test.benchmark.drift import DriftAlert
    from test.benchmark.metrics import ScenarioResult


_VALID_GATES = frozenset({"smoke", "regression", "performance"})


def _build_report(
    runner_results: dict[str, list[ScenarioResult]],
    gate: str,
    wall_ms_by_runner: dict[str, float],
) -> BenchmarkReport:
    all_results = [r for results in runner_results.values() for r in results]
    total = len(all_results)
    passed = sum(1 for r in all_results if r.status == "done")
    failed = total - passed
    total_wall = sum(wall_ms_by_runner.values())
    slowest = max(wall_ms_by_runner, key=wall_ms_by_runner.get) if wall_ms_by_runner else ""

    return BenchmarkReport(
        run_at=datetime.now(timezone.utc).isoformat(),
        gate=gate,
        runner_results=runner_results,
        total_scenarios=total,
        passed=passed,
        failed=failed,
        pass_rate=passed / total if total > 0 else 0.0,
        total_wall_ms=total_wall,
        slowest_runner=slowest,
    )


class BenchmarkSuite:
    """
    Top-level orchestrator for the benchmark framework.

    Usage:
        suite = (
            BenchmarkSuite()
            .register(ScenarioFileRunner(scenarios_dir))
            .register(TaoLoopRunner(regression_dir))
            .register(ParserRegressionRunner())
        )
        report = suite.run(gate="regression")
        alerts = suite.check_drift(report, Path(".react/benchmark/history.json"))

    Runners are executed in registration order.  gate=None runs all runners.
    """

    _GATES = ("smoke", "regression", "performance")

    def __init__(self) -> None:
        self._runners: list[BenchmarkRunner] = []

    def register(self, runner: BenchmarkRunner) -> "BenchmarkSuite":
        self._runners.append(runner)
        return self

    def runners(self) -> list[BenchmarkRunner]:
        return list(self._runners)

    # ── Execution ─────────────────────────────────────────────────────────────

    def run(self, gate: str | None = None) -> BenchmarkReport:
        """
        Execute all registered runners matching *gate*.

        gate=None         → run every registered runner
        gate="smoke"      → only smoke-level runners
        gate="regression" → only regression-level runners
        gate="performance"→ only performance-level runners
        """
        if gate is not None and gate not in _VALID_GATES:
            raise ValueError(
                f"Unknown gate {gate!r}. Valid values: {sorted(_VALID_GATES)}"
            )

        active = [
            r for r in self._runners
            if gate is None or r.gate == gate
        ]

        runner_results: dict[str, list[ScenarioResult]] = {}
        wall_ms_by_runner: dict[str, float] = {}

        for runner in active:
            t0 = time.perf_counter()
            runner_results[runner.name] = runner.run_all()
            wall_ms_by_runner[runner.name] = (time.perf_counter() - t0) * 1000

        return _build_report(runner_results, gate or "all", wall_ms_by_runner)

    # ── Drift ─────────────────────────────────────────────────────────────────

    def check_drift(
        self,
        report: BenchmarkReport,
        history_path: Path,
        threshold: float = 0.20,
        min_history_runs: int = 3,
    ) -> list[DriftAlert]:
        """
        Compare report against rolling history, append run to history, and
        return any DriftAlert objects.  The alerts are also stored on the
        report's drift_alerts field for convenience.
        """
        from dataclasses import asdict

        from test.benchmark.drift import append_history, check_drift, load_history

        history = load_history(history_path)
        flat = [asdict(r) for r in report.flat_results()]

        alerts = check_drift(
            flat,
            history,
            threshold=threshold,
            min_history_runs=min_history_runs,
        )
        report.drift_alerts = alerts
        append_history(history_path, flat)
        return alerts

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, report: BenchmarkReport, output: Path) -> None:
        """Write JSON report and a companion Markdown summary."""
        from test.benchmark.reporter import save_report, to_markdown

        output.parent.mkdir(parents=True, exist_ok=True)
        save_report(report.flat_results(), output)

        md_path = output.with_suffix(".md")
        md_path.write_text(to_markdown(report.flat_results()), encoding="utf-8")

    def to_markdown(self, report: BenchmarkReport) -> str:
        from test.benchmark.reporter import to_markdown
        return to_markdown(report.flat_results())
