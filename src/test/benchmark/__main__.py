"""
Benchmark CLI entry point.

    python -m test.benchmark run [--gate smoke|regression|performance|all]
                                 [--output PATH]
                                 [--history PATH]
                                 [--threshold FLOAT]
                                 [--fail-on-drift]

    python -m test.benchmark list
        List all registered runners and their gate levels.

    python -m test.benchmark report <json_path>
        Render an existing JSON report as Markdown.

Exit codes:
    0   all scenarios passed (and no drift if --fail-on-drift)
    1   one or more scenarios failed, or drift detected with --fail-on-drift
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ── Default paths ──────────────────────────────────────────────────────────────

def _default_output() -> Path:
    from config.storage import StorageConfig
    return Path(StorageConfig().benchmark_dir) / "report.json"


def _default_history() -> Path:
    from config.storage import StorageConfig
    return Path(StorageConfig().benchmark_dir) / "history.json"


def _default_scenarios_dir() -> Path:
    return Path(__file__).resolve().parent / "scenarios"


# ── Suite factory ──────────────────────────────────────────────────────────────

def _build_suite(scenarios_dir: Path) -> "BenchmarkSuite":
    from test.benchmark.runner import ScenarioFileRunner
    from test.benchmark.suite import BenchmarkSuite

    suite = BenchmarkSuite()
    suite.register(ScenarioFileRunner(scenarios_dir))

    # Conditionally register heavier runners if their dependencies are available.
    try:
        from test.benchmark.atomic_tool_runner import AtomicToolRunner
        suite.register(AtomicToolRunner())
    except ImportError:
        pass

    try:
        from test.benchmark.tao_runner import TaoLoopRunner
        suite.register(TaoLoopRunner(scenarios_dir))
    except (ImportError, OSError):
        pass

    try:
        from test.benchmark.parser_runner import ParserRegressionRunner
        suite.register(ParserRegressionRunner())
    except (ImportError, OSError):
        pass

    try:
        from test.benchmark.cluster_runner import ClusterRunner
        cluster_dir = Path(__file__).resolve().parent / "scenarios" / "cluster"
        suite.register(ClusterRunner(cluster_dir))
    except (ImportError, OSError):
        pass

    return suite


# ── Subcommand handlers ────────────────────────────────────────────────────────

def _cmd_run(args: argparse.Namespace) -> int:
    from test.benchmark.suite import BenchmarkSuite

    suite = _build_suite(Path(args.scenarios_dir))
    gate = None if args.gate == "all" else args.gate

    print(f"Running benchmark  gate={args.gate}  runners={len(suite.runners())}")
    report = suite.run(gate=gate)

    # Drift detection
    history_path = Path(args.history)
    alerts = suite.check_drift(
        report,
        history_path,
        threshold=args.threshold,
    )

    # Persist
    output = Path(args.output)
    suite.save(report, output)

    # Summary
    _print_summary(report)

    if alerts:
        print(f"\n{'─' * 60}")
        print(f"  {len(alerts)} DRIFT ALERT(S)")
        print(f"{'─' * 60}")
        for a in alerts:
            print(f"  {a}")
        print(f"{'─' * 60}")

    # Also write to GitHub Step Summary if available
    import os
    gss = os.environ.get("GITHUB_STEP_SUMMARY")
    if gss and gss != "/dev/null":
        md = suite.to_markdown(report)
        with open(gss, "a", encoding="utf-8") as f:
            f.write(md + "\n")

    if not report.all_passed:
        return 1
    if args.fail_on_drift and report.has_drift:
        return 1
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    suite = _build_suite(Path(args.scenarios_dir))
    print(f"{'Runner':<30}  {'Gate':<14}  Description")
    print("─" * 80)
    for r in suite.runners():
        print(f"  {r.name:<28}  {r.gate:<14}  {r.describe()}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from test.benchmark.reporter import load_report, to_markdown
    from test.benchmark.metrics import CallMetrics, ScenarioResult, ToolMetrics

    raw = load_report(Path(args.json_path))
    results: list[ScenarioResult] = []
    for d in raw:
        llm_calls = [CallMetrics(**c) for c in d.pop("llm_calls", [])]
        tool_calls = [ToolMetrics(**t) for t in d.pop("tool_calls", [])]
        results.append(ScenarioResult(**d, llm_calls=llm_calls, tool_calls=tool_calls))

    print(to_markdown(results))
    return 0


# ── Summary printer ────────────────────────────────────────────────────────────

def _print_summary(report: "BenchmarkReport") -> None:
    icon = "OK" if report.all_passed else "FAIL"
    print(f"\n[{icon}] {report.passed}/{report.total_scenarios} passed"
          f"  pass_rate={report.pass_rate:.0%}"
          f"  wall={report.total_wall_ms:.0f}ms"
          f"  slowest_runner={report.slowest_runner!r}")

    for runner_name, results in report.runner_results.items():
        p = sum(1 for r in results if r.status == "done")
        print(f"    {runner_name:<28}  {p}/{len(results)} passed")


# ── Argument parsing ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m test.benchmark",
        description="ReAct Benchmark CI/CD quality gate",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── run ───────────────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Execute benchmark suite")
    run_p.add_argument(
        "--gate",
        choices=["smoke", "regression", "performance", "all"],
        default="all",
        help="Gate level to run (default: all)",
    )
    run_p.add_argument(
        "--output", default=str(_default_output()),
        help="Output JSON report path",
    )
    run_p.add_argument(
        "--history", default=str(_default_history()),
        help="History JSON path for drift detection",
    )
    run_p.add_argument(
        "--scenarios-dir", default=str(_default_scenarios_dir()),
        dest="scenarios_dir",
        help="Directory containing YAML scenario files",
    )
    run_p.add_argument(
        "--threshold", type=float, default=0.20,
        help="Drift fraction threshold (default: 0.20 = 20%%)",
    )
    run_p.add_argument(
        "--fail-on-drift", action="store_true", dest="fail_on_drift",
        help="Exit 1 when drift is detected",
    )

    # ── list ──────────────────────────────────────────────────────────────────
    list_p = sub.add_parser("list", help="List registered runners")
    list_p.add_argument(
        "--scenarios-dir", default=str(_default_scenarios_dir()),
        dest="scenarios_dir",
    )

    # ── report ────────────────────────────────────────────────────────────────
    report_p = sub.add_parser("report", help="Render existing JSON report as Markdown")
    report_p.add_argument("json_path", help="Path to benchmark-report.json")

    args = parser.parse_args()

    handlers = {"run": _cmd_run, "list": _cmd_list, "report": _cmd_report}
    sys.exit(handlers[args.cmd](args))


if __name__ == "__main__":
    main()
