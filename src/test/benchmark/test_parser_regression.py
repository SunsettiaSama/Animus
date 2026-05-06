"""
Parser regression tests — exercised via ParserRegressionRunner.

Each test case locks in a specific parse_llm_output behaviour that was
introduced or fixed.  Failures here indicate a parser regression.

These tests also feed into the benchmark report (via benchmark_results
fixture) so quality_score drift across runs is tracked in history.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from test.benchmark.parser_runner import ParserRegressionRunner, ParseQuality, _CASES, _run_case, parse_llm_output


# ── Parametric test over all registered cases ─────────────────────────────────

@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.name)
def test_parser_case(case, benchmark_results: list) -> None:
    result = _run_case(case)
    benchmark_results.append(result)
    assert result.status == "done", (
        f"[{case.name}] parser case failed: {result.error}"
    )
    assert result.quality_score == 1.0, (
        f"[{case.name}] quality_score={result.quality_score} — {result.error}"
    )


# ── Focused assertions for today's parser fixes ───────────────────────────────

def test_single_quote_json_parses_clean() -> None:
    """
    ast.literal_eval fallback (Pass 4) must handle Python-style single-quote
    dicts.  Before the fix, {'answer': '42'} caused FINISH_DEGRADED because
    json.loads rejects single quotes.  After the fix it should be CLEAN.
    """
    raw = (
        "Thought: I know the answer.\n"
        "Action: finish\n"
        "Action Input: {'answer': '42'}"
    )
    result = parse_llm_output(raw)
    assert result.is_finish
    assert result.quality == ParseQuality.CLEAN, (
        f"Expected CLEAN but got {result.quality} — ast.literal_eval fix may be broken"
    )
    assert result.action_input.get("answer") == "42"


def test_garbled_action_input_is_finish_degraded() -> None:
    """
    Completely garbled Action Input (not parseable by any strategy) must
    produce ParseQuality.FINISH_DEGRADED so the upper-layer repair chain
    can trigger L2 correction.
    """
    raw = (
        "Thought: The answer is obvious.\n"
        "Action: finish\n"
        "Action Input: not valid json at all"
    )
    result = parse_llm_output(raw)
    assert result.is_finish
    assert result.quality == ParseQuality.FINISH_DEGRADED, (
        f"Expected FINISH_DEGRADED but got {result.quality}"
    )


def test_no_action_produces_implicit_finish() -> None:
    """
    Free-form LLM output with no ReAct labels must be treated as an implicit
    finish (is_finish=True, quality=FAILED) rather than triggering an error.
    """
    raw = "The answer is 42."
    result = parse_llm_output(raw)
    assert result.is_finish
    assert result.quality == ParseQuality.FAILED


def test_runner_all_cases_pass() -> None:
    """Smoke: ParserRegressionRunner.run_all() should return all-done results."""
    runner = ParserRegressionRunner()
    results = runner.run_all()
    assert len(results) == len(_CASES)
    failed = [r for r in results if r.status != "done"]
    assert not failed, (
        f"{len(failed)} parser case(s) failed: {[r.scenario for r in failed]}"
    )
