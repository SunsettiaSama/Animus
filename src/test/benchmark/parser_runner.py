"""
ParserRegressionRunner — regression-gate BenchmarkRunner that wraps
parse_llm_output unit cases as ScenarioResult objects.

Each test case calls parse_llm_output directly (no LLM, no network) and
maps pass/fail to ScenarioResult.status.  This brings parser regressions
into the unified report and drift detection pipeline alongside scenario-
based tests, so a future parser change that degrades quality_score shows
up in history.json and triggers a DriftAlert.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from test.benchmark.metrics import ScenarioResult

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Import parser.py directly via importlib to avoid running the
# agent.react.prompt package __init__.py, which imports block.py →
# memory chain → torch (breaks in environments where torch is unavailable).
# We register the module under its real dotted name so that @dataclass (which
# looks up cls.__module__ in sys.modules) and other internal cross-references
# work correctly.
import importlib.util as _ilu

_PARSER_MOD_NAME = "agent.react.prompt.parser"
_PARSER_FILE = _SRC / "agent" / "react" / "prompt" / "parser.py"

if _PARSER_MOD_NAME not in sys.modules:
    import types as _types

    # Stub out ancestor packages so Python can resolve the dotted path without
    # triggering their real __init__.py files (which pull in torch transitively).
    for _pkg in ("agent", "agent.react", "agent.react.prompt"):
        if _pkg not in sys.modules:
            _stub = _types.ModuleType(_pkg)
            _stub.__path__ = [str(_SRC / Path(*_pkg.split(".")))]  # type: ignore[assignment]
            _stub.__package__ = _pkg
            sys.modules[_pkg] = _stub

    _spec = _ilu.spec_from_file_location(_PARSER_MOD_NAME, _PARSER_FILE)
    _parser_mod = _ilu.module_from_spec(_spec)          # type: ignore[arg-type]
    sys.modules[_PARSER_MOD_NAME] = _parser_mod         # register BEFORE exec so @dataclass works
    _spec.loader.exec_module(_parser_mod)               # type: ignore[union-attr]

ParseQuality = sys.modules[_PARSER_MOD_NAME].ParseQuality
parse_llm_output = sys.modules[_PARSER_MOD_NAME].parse_llm_output


@dataclass
class _Case:
    name: str
    raw: str
    expected_action: str
    expected_quality: str        # ParseQuality.value string
    expected_answer: str | None  # None means "don't check"


# ---------------------------------------------------------------------------
# Test-case registry
# Each entry locks in the expected behaviour for a specific parse scenario.
# Add new cases here whenever a parser bug is fixed; the case name will
# appear in benchmark reports and drift history.
# ---------------------------------------------------------------------------
_CASES: list[_Case] = [
    # ── ast.literal_eval fix: single-quote JSON should now parse CLEAN ────────
    _Case(
        name="parser_single_quote_json",
        raw=(
            "Thought: I know the answer.\n"
            "Action: finish\n"
            "Action Input: {'answer': '42'}"
        ),
        expected_action="finish",
        expected_quality="clean",   # ast.literal_eval restores to CLEAN
        expected_answer="42",
    ),
    # ── FINISH_DEGRADED: garbled Action Input falls back to thought ───────────
    _Case(
        name="parser_finish_degraded_garbled",
        raw=(
            "Thought: The answer is obvious.\n"
            "Action: finish\n"
            "Action Input: not valid json at all"
        ),
        expected_action="finish",
        expected_quality="finish_degraded",
        expected_answer=None,   # answer content from thought; we only check quality
    ),
    # ── CLEAN tool call ───────────────────────────────────────────────────────
    _Case(
        name="parser_clean_tool_call",
        raw=(
            'Thought: I need to search.\n'
            'Action: web_search\n'
            'Action Input: {"query": "test"}'
        ),
        expected_action="web_search",
        expected_quality="clean",
        expected_answer=None,
    ),
    # ── Implicit finish (no Action line) → FAILED quality, is_finish=True ────
    _Case(
        name="parser_implicit_finish_no_action",
        raw="The answer is 42.",
        expected_action="finish",
        expected_quality="failed",
        expected_answer=None,
    ),
    # ── LENIENT: action inferred from verb heuristic ──────────────────────────
    _Case(
        name="parser_lenient_verb_inference",
        raw=(
            'Thought: I will use web_search to find the answer.\n'
            'Action Input: {"query": "hello"}'
        ),
        expected_action="web_search",
        expected_quality="lenient",
        expected_answer=None,
    ),
]


def _run_case(case: _Case) -> "ScenarioResult":
    from test.benchmark.metrics import MetricsCollector

    t0 = time.perf_counter()
    tool_names: frozenset[str] = frozenset({"web_search", "calculator", "finish"})
    result = parse_llm_output(case.raw, tool_names=tool_names)
    wall_ms = (time.perf_counter() - t0) * 1000

    # Evaluate pass/fail
    ok = True
    if result.action != case.expected_action:
        ok = False
    if result.quality.value != case.expected_quality:
        ok = False
    if (
        case.expected_answer is not None
        and result.action_input.get("answer") != case.expected_answer
    ):
        ok = False

    collector = MetricsCollector(case.name)
    # Simulate a single near-instant "LLM call" (the parse itself)
    collector.record_llm_call(
        call_id=case.name[:8],
        prompt_tokens=len(case.raw.split()),
        completion_tokens=0,
        latency_ms=wall_ms,
        ttfb_ms=0.0,
        success=ok,
    )
    collector.mark_step(0)
    if ok:
        collector.mark_done("ok")
    else:
        collector.mark_failed(
            "assertion",
            error=(
                f"action={result.action!r} (expected {case.expected_action!r}), "
                f"quality={result.quality.value!r} (expected {case.expected_quality!r})"
            ),
        )

    return collector.finalize(quality_score=1.0 if ok else 0.0)


class ParserRegressionRunner:
    """
    BenchmarkRunner that runs parse_llm_output unit regression cases.

    All cases run in-process with no external dependencies.  Adding a new
    parser regression test requires only a new _Case entry in _CASES above.
    """

    name = "parser_regression"
    gate = "regression"

    def run_all(self) -> list[ScenarioResult]:
        return [_run_case(c) for c in _CASES]

    def describe(self) -> str:
        return f"{len(_CASES)} parse_llm_output regression case(s)"
