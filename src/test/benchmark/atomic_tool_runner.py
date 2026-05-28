"""
AtomicToolRunner �?smoke-gate BenchmarkRunner that directly calls real tool
implementations without any LLM or TaoLoop involved.

Each test case:
  1. Instantiates the real tool class.
  2. Calls execute(**args) �?goes through Pydantic validation.
  3. Asserts the output matches an expected substring or passes a predicate.
  4. Maps pass/fail to ScenarioResult so results enter the unified report.

This is the leanest correctness gate: zero network, zero model, zero I/O.
If a tool implementation regresses (wrong formula, validation error, etc.)
this runner catches it in <1 ms per case.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from test.benchmark.metrics import MetricsCollector, ScenarioResult
from test.probe import emit_metric, probe

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Test-case registry
# ---------------------------------------------------------------------------

@dataclass
class _ToolCase:
    name: str               # appears in benchmark report
    tool_cls_path: str      # e.g. "agent.react.action.tools.impl.calculator.CalculatorAction"
    args: dict              # kwargs forwarded to execute()
    expect: str | Callable[[str], bool]  # substring OR predicate(output) -> bool
    description: str = ""


def _import_cls(dotted: str):
    module, _, attr = dotted.rpartition(".")
    import importlib
    mod = importlib.import_module(module)
    return getattr(mod, attr)


_CASES: list[_ToolCase] = [
    # ── calculator ────────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_calculator_arithmetic",
        tool_cls_path="agent.react.action.tools.impl.calculator.CalculatorAction",
        args={"expression": "(123 + 456) * 2"},
        expect="1158",
        description="(123+456)*2 == 1158",
    ),
    _ToolCase(
        name="tool_calculator_sqrt",
        tool_cls_path="agent.react.action.tools.impl.calculator.CalculatorAction",
        args={"expression": "sqrt(144)"},
        expect="12",
        description="sqrt(144) == 12",
    ),
    _ToolCase(
        name="tool_calculator_pow",
        tool_cls_path="agent.react.action.tools.impl.calculator.CalculatorAction",
        args={"expression": "2 ** 10"},
        expect="1024",
        description="2**10 == 1024",
    ),
    # ── string_transform ──────────────────────────────────────────────────────
    _ToolCase(
        name="tool_string_upper",
        tool_cls_path="agent.react.action.tools.impl.string_tool.StringTransformAction",
        args={"text": "hello world", "operation": "upper"},
        expect="HELLO WORLD",
        description="upper('hello world')",
    ),
    _ToolCase(
        name="tool_string_reverse",
        tool_cls_path="agent.react.action.tools.impl.string_tool.StringTransformAction",
        args={"text": "abc", "operation": "reverse"},
        expect="cba",
        description="reverse('abc') == 'cba'",
    ),
    _ToolCase(
        name="tool_string_count_chars",
        tool_cls_path="agent.react.action.tools.impl.string_tool.StringTransformAction",
        args={"text": "banana", "operation": "count_chars", "char": "a"},
        expect="3",
        description="count_chars('banana', 'a') == 3",
    ),
    # ── base64 ────────────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_base64_encode",
        tool_cls_path="agent.react.action.tools.impl.string_tool.Base64Action",
        args={"text": "hello", "mode": "encode"},
        expect="aGVsbG8=",
        description="base64.encode('hello') == 'aGVsbG8='",
    ),
    _ToolCase(
        name="tool_base64_decode",
        tool_cls_path="agent.react.action.tools.impl.string_tool.Base64Action",
        args={"text": "aGVsbG8=", "mode": "decode"},
        expect="hello",
        description="base64.decode('aGVsbG8=') == 'hello'",
    ),
    # ── unit_converter ────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_unit_km_to_m",
        tool_cls_path="agent.react.action.tools.impl.unit_converter.UnitConverterAction",
        args={"value": 1.0, "from_unit": "km", "to_unit": "m"},
        expect="1000",
        description="1 km == 1000 m",
    ),
    _ToolCase(
        name="tool_unit_celsius_to_fahrenheit",
        tool_cls_path="agent.react.action.tools.impl.unit_converter.UnitConverterAction",
        args={"value": 100.0, "from_unit": "C", "to_unit": "F"},
        expect="212",
        description="100°C == 212°F",
    ),
    _ToolCase(
        name="tool_unit_kg_to_lb",
        tool_cls_path="agent.react.action.tools.impl.unit_converter.UnitConverterAction",
        args={"value": 1.0, "from_unit": "kg", "to_unit": "lb"},
        expect=lambda out: "2.2" in out,
        description="1 kg �?2.2046 lb",
    ),
    _ToolCase(
        name="tool_get_weekday",
        tool_cls_path="agent.react.action.tools.impl.datetime_tool.GetWeekdayAction",
        args={"date": "2026-01-01"},
        expect="星期�?,
        description="2026-01-01 is Thursday (星期�?",
    ),
    # ── datetime ──────────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_get_datetime_beijing",
        tool_cls_path="agent.react.action.tools.impl.datetime_tool.GetDatetimeAction",
        args={"tz": "beijing"},
        expect=lambda out: "UTC+8" in out,
        description="GetDatetime returns Beijing time with UTC+8 label",
    ),
    # ── hash ──────────────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_hash_sha256",
        tool_cls_path="agent.react.action.tools.impl.string_tool.HashAction",
        args={"text": "hello", "algorithm": "sha256"},
        expect="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        description="sha256('hello') well-known hash",
    ),
    _ToolCase(
        name="tool_hash_md5",
        tool_cls_path="agent.react.action.tools.impl.string_tool.HashAction",
        args={"text": "hello", "algorithm": "md5"},
        expect="5d41402abc4b2a76b9719d911017c592",
        description="md5('hello') well-known hash",
    ),
    # ── word_count ────────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_word_count",
        tool_cls_path="agent.react.action.tools.impl.word_count.WordCountAction",
        args={"text": "Hello world foo"},
        expect="3",
        description="'Hello world foo' has 3 English words",
    ),
    # ── json_query ────────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_json_query",
        tool_cls_path="agent.react.action.tools.impl.data_tool.JsonQueryAction",
        args={"data": '{"name":"Alice","age":30}', "path": "$.name"},
        expect="Alice",
        description="JSONPath $.name extracts 'Alice'",
    ),
    # ── regex_extract ─────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_regex_extract",
        tool_cls_path="agent.react.action.tools.impl.data_tool.RegexExtractAction",
        args={"text": "foo123bar456", "pattern": r"\d+"},
        expect="123",
        description="RegexExtract finds '123' in 'foo123bar456'",
    ),
    # ── text_diff ─────────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_text_diff_same",
        tool_cls_path="agent.react.action.tools.impl.data_tool.TextDiffAction",
        args={"text_a": "hello", "text_b": "hello"},
        expect="完全相同",
        description="TextDiff on identical strings returns '完全相同'",
    ),
    _ToolCase(
        name="tool_text_diff_different",
        tool_cls_path="agent.react.action.tools.impl.data_tool.TextDiffAction",
        args={"text_a": "hello", "text_b": "world"},
        expect="---",
        description="TextDiff on different strings returns unified diff",
    ),
    # ── random ────────────────────────────────────────────────────────────────
    _ToolCase(
        name="tool_random_number",
        tool_cls_path="agent.react.action.tools.impl.random_tool.RandomNumberAction",
        args={"min": 1, "max": 100},
        expect=lambda out: "随机整数" in out,
        description="RandomNumber returns an integer in range",
    ),
    _ToolCase(
        name="tool_random_choice",
        tool_cls_path="agent.react.action.tools.impl.random_tool.RandomChoiceAction",
        args={"options": "apple,banana,cherry"},
        expect=lambda out: any(x in out for x in ["apple", "banana", "cherry"]),
        description="RandomChoice picks one of the given options",
    ),
    _ToolCase(
        name="tool_generate_uuid",
        tool_cls_path="agent.react.action.tools.impl.random_tool.GenerateUUIDAction",
        args={},
        expect=lambda out: len(out) > 30 and "-" in out,
        description="GenerateUUID returns a UUID string",
    ),
]


def _run_case(case: _ToolCase) -> ScenarioResult:
    collector = MetricsCollector(case.name)
    collector.mark_step(0)
    t0 = time.perf_counter()

    tool_cls = _import_cls(case.tool_cls_path)

    # Apply @probe at call-site �?production tool code is never modified.
    # emit_metric() calls inside execute() (if any) are captured automatically.
    probed_execute = probe(
        description=case.description,
        name=case.name,
        tags=["atomic_tool", tool_cls.__name__],
    )(tool_cls().execute)

    output: str = probed_execute(**case.args)

    # Attach benchmark-level assertion result as a probe metric so it appears
    # in the WebUI alongside any domain metrics the tool may have emitted.
    if callable(case.expect):
        ok = case.expect(output)
    else:
        ok = case.expect in output

    # The probe already recorded the run; annotate with assertion outcome
    # via a second emit �?this is a post-call metric, so we emit it directly
    # onto the last recorded run rather than through the context.
    from test.probe import _runs
    if _runs:
        _runs[-1].metrics["assertion_ok"] = ok
        _runs[-1].metrics["expected"] = str(case.expect) if not callable(case.expect) else "<predicate>"

    wall_ms = (time.perf_counter() - t0) * 1000
    collector.record_llm_call(
        call_id=case.name[:8],
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=wall_ms,
        ttfb_ms=0.0,
        success=ok,
    )

    if ok:
        collector.mark_done(output)
    else:
        collector.mark_failed(
            "assertion",
            error=f"expected {case.expect!r} in output {output!r}",
        )

    result = collector.finalize(quality_score=1.0 if ok else 0.0)
    result.trace = {
        "input":      case.args,
        "output":     output,
        "elapsed_ms": round(wall_ms, 3),
        "tool":       tool_cls.__name__,
        "assertion":  "pass" if ok else "fail",
    }
    return result


class AtomicToolRunner:
    """
    BenchmarkRunner that directly exercises real tool implementations.

    Gate: smoke (fast, zero-network, instant feedback on every PR).

    Registered test cases cover: calculator, string_transform, base64,
    unit_converter, datetime �?the full set of deterministic built-in tools.
    Failures here indicate a tool-level regression, independent of LLM behaviour.
    """

    name = "atomic_tool"
    gate = "smoke"

    def run_all(self) -> list[ScenarioResult]:
        return [_run_case(c) for c in _CASES]

    def describe(self) -> str:
        return f"{len(_CASES)} direct tool execution case(s) (no LLM)"
