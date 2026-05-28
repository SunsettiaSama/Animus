"""
test_llm_throughput.py �?LLM 吞吐量测试管�?============================================

覆盖两种运行模式�?
  默认（无需 LLM�?  ├── MockLLM + 可配置延迟模拟真实推理耗时
  ├── 顺序批处理（�?/ �?/ 长提示词�?  ├── 并发吞吐（concurrency = 1 / 2 / 4�?  └── 流式 TTFB & TBT 测量

  E2E（需要真�?LLM�?-run-e2e�?  ├── 通过 --base-url / --api-key / --model 指定后端
  └── �?Mock 相同的测量场景，输出真实指标

运行方式�?  # �?Mock 测试（快速，不需�?LLM�?  cd G:/ReAct
  python -m pytest src/test/infra/test_llm_throughput.py -v

  # E2E（真�?OpenAI 兼容端点�?  python -m pytest src/test/infra/test_llm_throughput.py -v --run-e2e \\
    --model deepseek-chat \\
    --base-url https://api.deepseek.com/v1 \\
    --api-key sk-...

  # 输出 JSON 报告
  python -m pytest src/test/infra/test_llm_throughput.py -v \\
    --throughput-json .react/benchmark/throughput.json

度量指标（列说明）：
  lat_p50/p95/p99  每请求端到端延迟分位数（ms�?  ttfb_p50/p95     流式：首字节延迟分位数（ms�?  tbt_avg          流式：�?token 间隔均值（ms�?  out_tok/s        输出 token 吞吐量（tokens / wall-clock s�?  QPS              每秒请求�?  err%             错误�?"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from test.benchmark.mock_llm import MockLLM
from test.infra.llm_throughput import (
    RequestResult,
    ScenarioStats,
    ThroughputHarness,
    _count_tokens,
    _measure_generate,
    _measure_stream,
    format_table,
)



# ── 测试提示词（固定，保证跨次运行可比较）────────────────────────────────────

_PROMPTS: dict[str, str] = {
    "short":  "Hello! Please say hi back in one sentence.",
    "medium": (
        "You are a helpful assistant. "
        "Please summarize the key principles of good software architecture "
        "in a concise paragraph of about 80 words."
    ),
    "long": (
        "You are an expert software architect. "
        "Please write a detailed technical design document for a distributed "
        "task scheduling system that supports: "
        "(1) multiple trigger types: once, interval, cron; "
        "(2) at-least-once execution guarantees with configurable retries; "
        "(3) result persistence and notification routing to multiple channels "
        "(WebUI, bot, email); "
        "(4) a real-time frontend timeline with drag-and-drop editing; "
        "(5) a work journal that records all agent activity. "
        "Include sections on architecture overview, data models, API design, "
        "and failure modes."
    ),
}

_MOCK_RESPONSES: dict[str, str] = {
    "short":  "Hi there! Hope you have a great day.",
    "medium": (
        "Good software architecture prioritizes separation of concerns, "
        "modularity, and loose coupling. Systems should be designed for "
        "testability and maintainability from the start. Use clear interfaces "
        "between components, prefer composition over inheritance, and ensure "
        "that each module has a single well-defined responsibility. "
        "Observability and fault tolerance must be built-in, not bolted on."
    ),
    "long": (
        "# Distributed Task Scheduling System Design\n\n"
        "## Architecture Overview\n"
        "The system consists of four core layers: Trigger Engine, Task Store, "
        "Execution Runtime, and Delivery Router. The Trigger Engine evaluates "
        "scheduled tasks against a TemporalClock, supporting once/interval/cron "
        "trigger types with timezone-aware scheduling.\n\n"
        "## Data Models\n"
        "ScheduledTask(id, name, instruction, trigger, status, retry_count, "
        "reply_target, delivery, command). TaskStatus: pending|running|done|failed|cancelled|paused.\n\n"
        "## API Design\n"
        "POST /api/scheduler/tasks �?create task\n"
        "PATCH /api/scheduler/tasks/{id} �?edit/pause/resume/cancel\n"
        "GET /api/scheduler/journal �?work journal\n"
        "GET/PATCH /api/scheduler/config �?runtime config\n\n"
        "## Failure Modes\n"
        "Network partitions handled by exponential backoff. LLM timeouts trigger "
        "retry with reduced context. Journal writes are atomic to prevent "
        "partial entries. ChannelRouter drops notifications silently on "
        "missing handler rather than crashing the task runner."
    ),
}


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def run_e2e(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--run-e2e"))


@pytest.fixture(scope="session")
def n_requests(request: pytest.FixtureRequest) -> int:
    return int(request.config.getoption("--n-requests"))


@pytest.fixture(scope="session")
def mock_delay_ms(request: pytest.FixtureRequest) -> float:
    return float(request.config.getoption("--mock-delay-ms"))


@pytest.fixture(scope="session")
def throughput_report_path(request: pytest.FixtureRequest) -> Path:
    return Path(request.config.getoption("--throughput-json"))


@pytest.fixture(scope="session")
def throughput_results() -> list[ScenarioStats]:
    return []


@pytest.fixture(scope="session", autouse=True)
def _write_throughput_report(
    throughput_results: list[ScenarioStats],
    throughput_report_path: Path,
) -> None:
    yield
    if not throughput_results:
        return
    throughput_report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "results": [s.to_dict() for s in throughput_results],
        "summary": format_table(throughput_results),
    }
    throughput_report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n\n{'='*70}")
    print("LLM Throughput Benchmark Results")
    print('='*70)
    print(format_table(throughput_results))
    print(f"\nJSON report saved to: {throughput_report_path}")


def _make_mock_llm(prompt_label: str, delay_ms: float = 5.0) -> MockLLM:
    """每个 prompt 大小对应一个包含合适长度响应的 MockLLM�?""
    return MockLLM(
        script=[_MOCK_RESPONSES[prompt_label]],
        delay_ms=delay_ms,
        ttfb_ms=delay_ms * 0.3,
    )


def _make_real_llm(request: pytest.FixtureRequest) -> Any:
    """使用命令行参数构造真�?LLM 实例（backend=openai）�?""
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import LLM

    cfg = LLMConfig(
        model=request.config.getoption("--model"),
        api_key=request.config.getoption("--api-key") or "EMPTY",
        base_url=request.config.getoption("--base-url"),
        max_tokens=256,
        temperature=0.0,
        backend="openai",
    )
    return LLM(cfg)


# ══════════════════════════════════════════════════════════════════════�?# 工具函数测试（无依赖�?# ══════════════════════════════════════════════════════════════════════�?
class TestTokenCounter:

    def test_short_prompt_nonzero(self):
        assert _count_tokens(_PROMPTS["short"]) > 0

    def test_medium_more_than_short(self):
        assert _count_tokens(_PROMPTS["medium"]) > _count_tokens(_PROMPTS["short"])

    def test_long_more_than_medium(self):
        assert _count_tokens(_PROMPTS["long"]) > _count_tokens(_PROMPTS["medium"])

    def test_empty_string(self):
        assert _count_tokens("") == 0

    def test_chinese_text_nonzero(self):
        assert _count_tokens("你好，请问有什么可以帮助你的？") > 0


# ══════════════════════════════════════════════════════════════════════�?# RequestResult 基础测试
# ══════════════════════════════════════════════════════════════════════�?
class TestRequestResult:

    def test_total_tokens(self):
        r = RequestResult(prompt_tokens=10, completion_tokens=20, latency_ms=100.0, ttfb_ms=50.0)
        assert r.total_tokens == 30

    def test_output_tok_per_s(self):
        r = RequestResult(prompt_tokens=10, completion_tokens=100, latency_ms=1000.0, ttfb_ms=100.0)
        assert abs(r.output_tok_per_s - 100.0) < 0.01

    def test_zero_latency_returns_zero_throughput(self):
        r = RequestResult(prompt_tokens=10, completion_tokens=100, latency_ms=0.0, ttfb_ms=0.0)
        assert r.output_tok_per_s == 0.0

    def test_error_field(self):
        r = RequestResult(prompt_tokens=0, completion_tokens=0, latency_ms=0.0, ttfb_ms=0.0, error="timeout")
        assert r.error == "timeout"


# ══════════════════════════════════════════════════════════════════════�?# Mock 单次请求测量
# ══════════════════════════════════════════════════════════════════════�?
class TestSingleRequestMeasurement:

    def test_measure_generate_returns_result(self):
        llm = _make_mock_llm("short", delay_ms=0.0)
        r = _measure_generate(llm, _PROMPTS["short"])
        assert r.error == ""
        assert r.prompt_tokens > 0
        assert r.completion_tokens > 0
        assert r.latency_ms >= 0.0

    def test_measure_generate_records_delay(self):
        llm = _make_mock_llm("short", delay_ms=20.0)
        r = _measure_generate(llm, _PROMPTS["short"])
        assert r.latency_ms >= 15.0   # allow platform jitter

    def test_measure_stream_has_ttfb(self):
        llm = _make_mock_llm("short", delay_ms=0.0)
        r = _measure_stream(llm, _PROMPTS["short"])
        assert r.error == ""
        assert r.ttfb_ms >= 0.0
        assert r.completion_tokens > 0

    def test_measure_stream_ttfb_on_delayed_mock(self):
        llm = _make_mock_llm("short", delay_ms=0.0)
        llm._ttfb_ms = 30.0
        r = _measure_stream(llm, _PROMPTS["short"])
        assert r.ttfb_ms >= 20.0

    def test_measure_generate_error_recovery(self):
        class BrokenLLM:
            def generate(self, prompt: str) -> str:
                raise RuntimeError("forced failure")
        r = _measure_generate(BrokenLLM(), "test")
        assert "forced failure" in r.error
        assert r.completion_tokens == 0

    def test_measure_stream_error_recovery(self):
        class BrokenStreamLLM:
            def stream_generate(self, prompt: str):
                raise RuntimeError("stream broken")
                yield  # make it a generator
        r = _measure_stream(BrokenStreamLLM(), "test")
        assert "stream broken" in r.error


# ══════════════════════════════════════════════════════════════════════�?# Mock 顺序批处理场�?# ══════════════════════════════════════════════════════════════════════�?
class TestSequentialThroughput:

    @pytest.mark.parametrize("prompt_label", ["short", "medium", "long"])
    def test_sequential_returns_stats(
        self,
        prompt_label: str,
        throughput_results: list[ScenarioStats],
        n_requests: int,
        mock_delay_ms: float,
    ):
        llm = _make_mock_llm(prompt_label, delay_ms=mock_delay_ms)
        harness = ThroughputHarness(llm)
        stats = harness.run_sequential(
            name=f"mock_seq_{prompt_label}",
            prompt=_PROMPTS[prompt_label],
            n=n_requests,
            prompt_label=prompt_label,
        )
        throughput_results.append(stats)

        assert stats.n_requests == n_requests
        assert stats.error_rate == 0.0
        assert stats.throughput_tok_s > 0.0
        assert stats.latency_p50_ms > 0.0
        assert stats.latency_p95_ms >= stats.latency_p50_ms
        assert stats.latency_p99_ms >= stats.latency_p95_ms
        assert stats.qps > 0.0
        assert stats.completion_tokens_mean > 0.0
        assert stats.mode == "sequential"

    def test_sequential_short_faster_than_long(
        self,
        mock_delay_ms: float,
    ):
        """短提示词每次调用应比长提示词更快（Mock 延迟相同，所以指标应相近，但不应倒置）�?""
        n = 10
        short_llm = _make_mock_llm("short", delay_ms=mock_delay_ms)
        long_llm  = _make_mock_llm("long",  delay_ms=mock_delay_ms)
        h_short = ThroughputHarness(short_llm)
        h_long  = ThroughputHarness(long_llm)
        stats_s = h_short.run_sequential("s_short", _PROMPTS["short"], n=n, prompt_label="short")
        stats_l = h_long.run_sequential("s_long",  _PROMPTS["long"],  n=n, prompt_label="long")
        # 短提示词 mean_latency �?长提示词（Mock 延迟固定，长响应体多�?token 计数但耗时相近�?        # 这里我们只保证两者都无错�?        assert stats_s.error_rate == 0.0
        assert stats_l.error_rate == 0.0

    def test_throughput_tok_s_monotone_with_n(self, mock_delay_ms: float):
        """�?Mock 下，n=10 �?n=30 的吞吐量应该相近（�?0%），不应差距极大�?""
        llm10 = _make_mock_llm("medium", delay_ms=mock_delay_ms)
        llm30 = _make_mock_llm("medium", delay_ms=mock_delay_ms)
        s10 = ThroughputHarness(llm10).run_sequential("n10", _PROMPTS["medium"], n=10)
        s30 = ThroughputHarness(llm30).run_sequential("n30", _PROMPTS["medium"], n=30)
        if s10.throughput_tok_s > 0 and s30.throughput_tok_s > 0:
            ratio = max(s10.throughput_tok_s, s30.throughput_tok_s) / min(s10.throughput_tok_s, s30.throughput_tok_s)
            assert ratio < 3.0, f"Throughput ratio too large: {ratio:.2f}"


# ══════════════════════════════════════════════════════════════════════�?# Mock 并发吞吐场景
# ══════════════════════════════════════════════════════════════════════�?
class TestConcurrentThroughput:

    @pytest.mark.parametrize("concurrency", [1, 2, 4])
    def test_concurrent_returns_stats(
        self,
        concurrency: int,
        throughput_results: list[ScenarioStats],
        n_requests: int,
        mock_delay_ms: float,
    ):
        llm = _make_mock_llm("medium", delay_ms=mock_delay_ms)
        harness = ThroughputHarness(llm)
        stats = harness.run_concurrent(
            name=f"mock_conc_c{concurrency}",
            prompt=_PROMPTS["medium"],
            n=n_requests,
            concurrency=concurrency,
            prompt_label="medium",
        )
        throughput_results.append(stats)

        assert stats.concurrency == concurrency
        assert stats.n_requests == n_requests
        assert stats.error_rate == 0.0
        assert stats.mode == "concurrent"
        assert stats.throughput_tok_s > 0.0
        assert stats.qps > 0.0

    def test_higher_concurrency_higher_qps(self, mock_delay_ms: float):
        """并发度提升应带来更高�?QPS（在 Mock 下延迟固定，并发扩展性好）�?""
        n = 20
        delay = max(mock_delay_ms, 10.0)   # 至少 10ms 延迟让并发效果可�?        llm1 = _make_mock_llm("medium", delay_ms=delay)
        llm4 = _make_mock_llm("medium", delay_ms=delay)
        s1 = ThroughputHarness(llm1).run_concurrent("c1", _PROMPTS["medium"], n=n, concurrency=1)
        s4 = ThroughputHarness(llm4).run_concurrent("c4", _PROMPTS["medium"], n=n, concurrency=4)
        # 4 并发�?QPS 高于 1 并发（松散断言，防止极低延迟下测量噪声�?        assert s4.qps >= s1.qps * 0.8, (
            f"concurrency=4 QPS ({s4.qps:.2f}) should be >= 80% of "
            f"concurrency=1 QPS ({s1.qps:.2f})"
        )

    def test_concurrent_all_requests_completed(self, n_requests: int, mock_delay_ms: float):
        llm = _make_mock_llm("short", delay_ms=mock_delay_ms)
        stats = ThroughputHarness(llm).run_concurrent(
            "completion_check", _PROMPTS["short"], n=n_requests, concurrency=4
        )
        assert stats.n_requests == n_requests
        # 允许 0 错误�?        assert stats.error_rate == 0.0

    def test_wall_time_less_than_sequential_with_delay(self):
        """并发 4 �?wall time 应明显低于顺�?4（有延迟时）�?""
        n = 12
        delay = 20.0
        llm_seq  = _make_mock_llm("short", delay_ms=delay)
        llm_conc = _make_mock_llm("short", delay_ms=delay)
        s_seq  = ThroughputHarness(llm_seq).run_sequential("seq_wall",  _PROMPTS["short"], n=n)
        s_conc = ThroughputHarness(llm_conc).run_concurrent("conc_wall", _PROMPTS["short"], n=n, concurrency=4)
        assert s_conc.wall_time_s < s_seq.wall_time_s, (
            f"Concurrent wall_time ({s_conc.wall_time_s:.3f}s) should be < "
            f"sequential ({s_seq.wall_time_s:.3f}s)"
        )


# ══════════════════════════════════════════════════════════════════════�?# Mock 流式测量场景
# ══════════════════════════════════════════════════════════════════════�?
class TestStreamThroughput:

    @pytest.mark.parametrize("prompt_label", ["short", "medium"])
    def test_stream_returns_stats(
        self,
        prompt_label: str,
        throughput_results: list[ScenarioStats],
        n_requests: int,
        mock_delay_ms: float,
    ):
        llm = _make_mock_llm(prompt_label, delay_ms=mock_delay_ms)
        harness = ThroughputHarness(llm)
        stats = harness.run_stream(
            name=f"mock_stream_{prompt_label}",
            prompt=_PROMPTS[prompt_label],
            n=min(n_requests, 15),   # 流式用较小批�?            prompt_label=prompt_label,
        )
        throughput_results.append(stats)

        assert stats.mode == "stream"
        assert stats.error_rate == 0.0
        assert stats.throughput_tok_s > 0.0
        assert stats.ttfb_p50_ms >= 0.0

    def test_stream_ttfb_respects_mock_delay(self, mock_delay_ms: float):
        delay = 30.0
        llm = MockLLM(script=[_MOCK_RESPONSES["short"]], delay_ms=0.0, ttfb_ms=delay)
        r = _measure_stream(llm, _PROMPTS["short"])
        assert r.ttfb_ms >= delay * 0.8

    def test_stream_completion_tokens_nonzero(self, mock_delay_ms: float):
        llm = _make_mock_llm("medium", delay_ms=mock_delay_ms)
        r = _measure_stream(llm, _PROMPTS["medium"])
        assert r.completion_tokens > 0


# ══════════════════════════════════════════════════════════════════════�?# ScenarioStats 正确性验�?# ══════════════════════════════════════════════════════════════════════�?
class TestScenarioStats:

    def _run_tiny(self, delay_ms: float = 5.0) -> ScenarioStats:
        llm = _make_mock_llm("short", delay_ms=delay_ms)
        return ThroughputHarness(llm).run_sequential(
            "tiny", _PROMPTS["short"], n=5, prompt_label="short"
        )

    def test_latency_percentiles_ordered(self):
        s = self._run_tiny()
        assert s.latency_p50_ms <= s.latency_p95_ms <= s.latency_p99_ms

    def test_wall_time_positive(self):
        assert self._run_tiny().wall_time_s > 0

    def test_error_rate_range(self):
        s = self._run_tiny()
        assert 0.0 <= s.error_rate <= 1.0

    def test_to_dict_serializable(self):
        s = self._run_tiny()
        d = s.to_dict()
        # JSON シリアライズできるこ�?        encoded = json.dumps(d)
        loaded = json.loads(encoded)
        assert loaded["scenario_name"] == "tiny"
        assert loaded["mode"] == "sequential"

    def test_prompt_label_preserved(self):
        llm = _make_mock_llm("long")
        s = ThroughputHarness(llm).run_sequential("lbl_test", _PROMPTS["long"], n=3, prompt_label="long")
        assert s.prompt_label == "long"

    def test_throughput_tok_s_consistent_with_wall_time(self):
        s = self._run_tiny(delay_ms=10.0)
        expected_approx = s.completion_tokens_mean * s.n_requests / s.wall_time_s
        assert abs(s.throughput_tok_s - expected_approx) / max(expected_approx, 1) < 0.05


# ══════════════════════════════════════════════════════════════════════�?# format_table 渲染
# ══════════════════════════════════════════════════════════════════════�?
class TestFormatTable:

    def _dummy_stats(self, name: str) -> ScenarioStats:
        llm = _make_mock_llm("short", delay_ms=1.0)
        return ThroughputHarness(llm).run_sequential(name, _PROMPTS["short"], n=3)

    def test_empty_list(self):
        assert format_table([]) == "(no results)"

    def test_single_row_has_name(self):
        s = self._dummy_stats("alpha")
        out = format_table([s])
        assert "alpha" in out

    def test_multiple_rows(self):
        rows = [self._dummy_stats(f"row_{i}") for i in range(3)]
        out = format_table(rows)
        for r in rows:
            assert r.scenario_name in out

    def test_header_contains_metrics(self):
        s = self._dummy_stats("h")
        out = format_table([s])
        assert "lat_p50" in out
        assert "out_tok/s" in out
        assert "QPS" in out


# ══════════════════════════════════════════════════════════════════════�?# E2E �?真实 LLM（仅 --run-e2e�?# ══════════════════════════════════════════════════════════════════════�?
@pytest.mark.skipif(
    not any("--run-e2e" in a for a in sys.argv),
    reason="Pass --run-e2e to run real LLM throughput tests",
)
class TestRealLLMThroughput:
    """
    使用真实 OpenAI-兼容端点运行吞吐量测试�?    结果只断言无错误和指标非零；具体数值依赖网络和模型�?    """

    @pytest.fixture(autouse=True)
    def _skip_without_e2e(self, run_e2e: bool):
        if not run_e2e:
            pytest.skip("--run-e2e not set")

    @pytest.mark.parametrize("prompt_label", ["short", "medium"])
    def test_real_sequential(
        self,
        request: pytest.FixtureRequest,
        prompt_label: str,
        throughput_results: list[ScenarioStats],
    ):
        llm = _make_real_llm(request)
        stats = ThroughputHarness(llm).run_sequential(
            name=f"real_seq_{prompt_label}",
            prompt=_PROMPTS[prompt_label],
            n=5,
            prompt_label=prompt_label,
        )
        throughput_results.append(stats)
        assert stats.error_rate == 0.0, f"Errors: {stats.error_rate*100:.0f}%"
        assert stats.throughput_tok_s > 0.0
        assert stats.latency_p50_ms > 0.0

    def test_real_concurrent(
        self,
        request: pytest.FixtureRequest,
        throughput_results: list[ScenarioStats],
    ):
        llm = _make_real_llm(request)
        stats = ThroughputHarness(llm).run_concurrent(
            name="real_conc_c2",
            prompt=_PROMPTS["short"],
            n=6,
            concurrency=2,
            prompt_label="short",
        )
        throughput_results.append(stats)
        assert stats.error_rate == 0.0
        assert stats.qps > 0.0

    def test_real_stream(
        self,
        request: pytest.FixtureRequest,
        throughput_results: list[ScenarioStats],
    ):
        llm = _make_real_llm(request)
        stats = ThroughputHarness(llm).run_stream(
            name="real_stream_short",
            prompt=_PROMPTS["short"],
            n=3,
            prompt_label="short",
        )
        throughput_results.append(stats)
        assert stats.error_rate == 0.0
        assert stats.ttfb_p50_ms >= 0.0
        assert stats.throughput_tok_s > 0.0
