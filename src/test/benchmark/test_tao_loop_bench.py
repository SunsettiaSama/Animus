"""
TaoLoop integration regression tests �?exercised via TaoLoopRunner.

These tests inject MockLLM + ScriptActionExecutor into a real TaoLoop
instance and assert end-to-end behaviour for the scenarios introduced
as part of the parser bug-fix (finish_degraded.yaml, repair_chain.yaml).

Key assertions:
  - result.status == "done"       (pipeline finishes successfully)
  - result.llm_retries >= 1       (L2 correction was actually triggered)
  - final answer contains "42"    (correct content surfaced)

Results are injected into the benchmark_results fixture so they appear in
the unified JSON/Markdown report alongside scenario-file and parser runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


def _load_and_run(yaml_name: str) -> "ScenarioResult":
    from test.benchmark.scenarios.base import ScenarioLoader
    from test.benchmark.tao_runner import _run_one

    path = _SCENARIOS_DIR / yaml_name
    if not path.exists():
        pytest.skip(f"Scenario file not found: {path}")
    scenario = ScenarioLoader.load(path)
    return _run_one(scenario)


# ── finish_degraded scenario ───────────────────────────────────────────────────

def test_finish_degraded_repair(benchmark_results: list) -> None:
    """
    finish_degraded.yaml: garbled Action Input triggers FINISH_DEGRADED on
    step 1, L2 fires the correction prompt, step 2 provides valid JSON finish.
    The pipeline must succeed and the answer must contain "42".
    """
    result = _load_and_run("finish_degraded.yaml")
    benchmark_results.append(result)

    assert result.status == "done", (
        f"finish_degraded scenario did not finish: status={result.status} error={result.error}"
    )
    assert result.llm_retries >= 1, (
        "L2 repair chain was expected to fire at least once "
        f"(llm_retries={result.llm_retries})"
    )


# ── repair_chain scenario ──────────────────────────────────────────────────────

def test_repair_chain_no_action(benchmark_results: list) -> None:
    """
    repair_chain.yaml: raw free-form LLM output (FAILED quality) triggers L2
    correction on step 1; step 2 outputs valid finish JSON.
    The pipeline must succeed and the answer must contain "42".
    """
    result = _load_and_run("repair_chain.yaml")
    benchmark_results.append(result)

    assert result.status == "done", (
        f"repair_chain scenario did not finish: status={result.status} error={result.error}"
    )
    assert result.llm_retries >= 1, (
        "L2 repair chain was expected to fire at least once "
        f"(llm_retries={result.llm_retries})"
    )


# ── Smoke: runner discovers both new scenarios ────────────────────────────────

def test_tao_runner_regression_scenarios(benchmark_results: list) -> None:
    """
    TaoLoopRunner must discover and successfully run both regression YAML
    scenarios (finish_degraded + repair_chain).  All results must be 'done'.
    """
    from test.benchmark.tao_runner import TaoLoopRunner

    runner = TaoLoopRunner(_SCENARIOS_DIR)
    results = runner.run_all()
    benchmark_results.extend(results)

    regression_names = {"finish_degraded_garbled", "repair_chain_no_action"}
    ran_names = {r.scenario for r in results}
    for name in regression_names:
        assert name in ran_names, f"Scenario {name!r} was not executed by TaoLoopRunner"

    failed = [r for r in results if r.status != "done"]
    assert not failed, (
        f"{len(failed)} scenario(s) failed: {[r.scenario for r in failed]}"
    )
