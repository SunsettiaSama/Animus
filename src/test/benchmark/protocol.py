from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from test.benchmark.drift import DriftAlert
    from test.benchmark.metrics import ScenarioResult


@runtime_checkable
class BenchmarkRunner(Protocol):
    """
    Extension protocol for the benchmark framework.

    Any object that satisfies this structural interface is a valid runner.
    Runners are the sole extension point: to benchmark a new subsystem,
    implement this protocol and register the runner with BenchmarkSuite.

    gate values:
      "smoke"       �?fast, zero-network; run on every PR
      "regression"  �?full pipeline; run on every merge to main
      "performance" �?latency/token-budget tracking; run nightly
    """

    name: str
    gate: str

    def run_all(self) -> list[ScenarioResult]: ...
    def describe(self) -> str: ...


@dataclass
class BenchmarkReport:
    """
    Single aggregation point for an entire benchmark run.

    runner_results holds per-runner raw ScenarioResult lists so downstream
    tools (reporter, drift detector) can slice any way they need.
    The aggregate fields give a quick pass/fail signal for CD gates.
    """

    run_at: str
    gate: str
    runner_results: dict[str, list[ScenarioResult]]

    # ── Cross-runner aggregate ────────────────────────────────────────────────
    total_scenarios: int
    passed: int
    failed: int
    pass_rate: float        # passed / total_scenarios  (0.0�?.0)
    total_wall_ms: float
    slowest_runner: str     # name of the runner with highest sum(wall_ms)

    drift_alerts: list[DriftAlert] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.drift_alerts)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    def flat_results(self) -> list[ScenarioResult]:
        """Flatten all runner results into a single ordered list."""
        out: list[ScenarioResult] = []
        for results in self.runner_results.values():
            out.extend(results)
        return out
