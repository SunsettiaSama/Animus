"""
llm_throughput.py — LLM 吞吐量测量引擎
========================================

独立于 pytest 的纯 Python 测量核心，可以在测试和脚本中复用。

测量指标：
  - 顺序批处理：tokens/s、延迟分布 (p50 / p95 / p99)
  - 并发吞吐：在给定并发度下的整体 tokens/s、QPS
  - 流式 TTFB（首字节延迟）、TBT（逐 token 间隔时间）
  - 每次请求的 prompt_tokens / completion_tokens / latency_ms
"""

from __future__ import annotations

import concurrent.futures
import math
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generator, Sequence


# ── Token 计数（复用 benchmark tokenizer）────────────────────────────────────

def _count_tokens(text: str) -> int:
    from test.benchmark.tokenizer import count_tokens
    return count_tokens(text)


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class RequestResult:
    """单次 LLM 调用的测量结果。"""
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    ttfb_ms: float           # 流式：首 token 延迟；非流式 == latency_ms
    tbt_values_ms: list[float] = field(default_factory=list)   # 逐 token 时间间隔
    error: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def output_tok_per_s(self) -> float:
        if self.latency_ms <= 0:
            return 0.0
        return self.completion_tokens / (self.latency_ms / 1000.0)


@dataclass
class ScenarioStats:
    """一个场景（批量 or 并发）的统计摘要。"""
    scenario_name: str
    mode: str                     # "sequential" | "concurrent" | "stream"
    n_requests: int
    concurrency: int
    prompt_label: str             # "short" / "medium" / "long"
    prompt_tokens_mean: float
    completion_tokens_mean: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_mean_ms: float
    ttfb_p50_ms: float
    ttfb_p95_ms: float
    tbt_mean_ms: float            # 0.0 if non-streaming
    throughput_tok_s: float       # 输出 tokens / 总耗时（wall-clock）
    qps: float                    # 请求数 / 总耗时（wall-clock）
    error_rate: float             # 0.0 – 1.0
    wall_time_s: float

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ── 统计工具 ──────────────────────────────────────────────────────────────────

def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = (len(s) - 1) * p / 100
    lo = int(idx)
    hi = lo + 1
    frac = idx - lo
    if hi >= len(s):
        return s[-1]
    return s[lo] + frac * (s[hi] - s[lo])


def _summarise(
    name: str,
    mode: str,
    concurrency: int,
    prompt_label: str,
    results: list[RequestResult],
    wall_s: float,
) -> ScenarioStats:
    ok = [r for r in results if not r.error]
    errors = len(results) - len(ok)

    lats = [r.latency_ms for r in ok]
    ttfbs = [r.ttfb_ms for r in ok]
    tbt_all = [ms for r in ok for ms in r.tbt_values_ms]
    total_out = sum(r.completion_tokens for r in ok)

    return ScenarioStats(
        scenario_name=name,
        mode=mode,
        n_requests=len(results),
        concurrency=concurrency,
        prompt_label=prompt_label,
        prompt_tokens_mean=statistics.mean([r.prompt_tokens for r in ok]) if ok else 0.0,
        completion_tokens_mean=statistics.mean([r.completion_tokens for r in ok]) if ok else 0.0,
        latency_p50_ms=_percentile(lats, 50),
        latency_p95_ms=_percentile(lats, 95),
        latency_p99_ms=_percentile(lats, 99),
        latency_mean_ms=statistics.mean(lats) if lats else 0.0,
        ttfb_p50_ms=_percentile(ttfbs, 50),
        ttfb_p95_ms=_percentile(ttfbs, 95),
        tbt_mean_ms=statistics.mean(tbt_all) if tbt_all else 0.0,
        throughput_tok_s=total_out / wall_s if wall_s > 0 else 0.0,
        qps=len(ok) / wall_s if wall_s > 0 else 0.0,
        error_rate=errors / len(results) if results else 0.0,
        wall_time_s=wall_s,
    )


# ── 单次请求测量 ──────────────────────────────────────────────────────────────

def _measure_generate(llm: Any, prompt: str) -> RequestResult:
    pt = _count_tokens(prompt)
    t0 = time.perf_counter()
    try:
        output = llm.generate(prompt)
    except Exception as exc:
        return RequestResult(
            prompt_tokens=pt, completion_tokens=0,
            latency_ms=0.0, ttfb_ms=0.0, error=str(exc),
        )
    lat = (time.perf_counter() - t0) * 1000
    ct = _count_tokens(output)
    return RequestResult(
        prompt_tokens=pt, completion_tokens=ct,
        latency_ms=lat, ttfb_ms=lat,
    )


def _measure_stream(llm: Any, prompt: str) -> RequestResult:
    pt = _count_tokens(prompt)
    t0 = time.perf_counter()
    ttfb_ms = 0.0
    tbt_vals: list[float] = []
    chunks: list[str] = []
    last_ts = t0
    try:
        for chunk in llm.stream_generate(prompt):
            now = time.perf_counter()
            if not chunks:
                ttfb_ms = (now - t0) * 1000
            else:
                tbt_vals.append((now - last_ts) * 1000)
            last_ts = now
            chunks.append(chunk)
    except Exception as exc:
        return RequestResult(
            prompt_tokens=pt, completion_tokens=0,
            latency_ms=0.0, ttfb_ms=0.0, error=str(exc),
        )
    lat = (time.perf_counter() - t0) * 1000
    output = "".join(chunks)
    ct = _count_tokens(output)
    return RequestResult(
        prompt_tokens=pt, completion_tokens=ct,
        latency_ms=lat, ttfb_ms=ttfb_ms,
        tbt_values_ms=tbt_vals,
    )


# ── 吞吐量场景执行器 ──────────────────────────────────────────────────────────

class ThroughputHarness:
    """
    可复用的吞吐量测量驱动。

    Usage::

        harness = ThroughputHarness(llm)
        stats = harness.run_sequential("my_scenario", prompt, n=20)
        stats = harness.run_concurrent("concurrent_4", prompt, n=20, concurrency=4)
        stats = harness.run_stream("stream_scenario", prompt, n=10)
    """

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def run_sequential(
        self,
        name: str,
        prompt: str,
        n: int = 20,
        prompt_label: str = "custom",
    ) -> ScenarioStats:
        results: list[RequestResult] = []
        t_start = time.perf_counter()
        for _ in range(n):
            results.append(_measure_generate(self._llm, prompt))
        wall = time.perf_counter() - t_start
        return _summarise(name, "sequential", 1, prompt_label, results, wall)

    def run_concurrent(
        self,
        name: str,
        prompt: str,
        n: int = 20,
        concurrency: int = 4,
        prompt_label: str = "custom",
    ) -> ScenarioStats:
        results: list[RequestResult] = [RequestResult(0, 0, 0.0, 0.0)] * n
        t_start = time.perf_counter()

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            futs = {ex.submit(_measure_generate, self._llm, prompt): i for i in range(n)}
            for fut in concurrent.futures.as_completed(futs):
                idx = futs[fut]
                try:
                    results[idx] = fut.result()
                except Exception as exc:
                    results[idx] = RequestResult(0, 0, 0.0, 0.0, error=str(exc))

        wall = time.perf_counter() - t_start
        return _summarise(name, "concurrent", concurrency, prompt_label, results, wall)

    def run_stream(
        self,
        name: str,
        prompt: str,
        n: int = 10,
        prompt_label: str = "custom",
    ) -> ScenarioStats:
        results: list[RequestResult] = []
        t_start = time.perf_counter()
        for _ in range(n):
            results.append(_measure_stream(self._llm, prompt))
        wall = time.perf_counter() - t_start
        return _summarise(name, "stream", 1, prompt_label, results, wall)


# ── 报告渲染 ──────────────────────────────────────────────────────────────────

def format_table(stats_list: list[ScenarioStats]) -> str:
    if not stats_list:
        return "(no results)"

    header = (
        f"{'Scenario':<35} {'Mode':<12} {'Conc':>4} "
        f"{'N':>4} {'lat_p50':>8} {'lat_p95':>8} {'lat_p99':>8} "
        f"{'ttfb_p50':>8} {'tbt_avg':>7} "
        f"{'out_tok/s':>10} {'QPS':>7} {'err%':>5}"
    )
    sep = "-" * len(header)
    rows = [header, sep]
    for s in stats_list:
        rows.append(
            f"{s.scenario_name:<35} {s.mode:<12} {s.concurrency:>4} "
            f"{s.n_requests:>4} {s.latency_p50_ms:>8.1f} {s.latency_p95_ms:>8.1f} {s.latency_p99_ms:>8.1f} "
            f"{s.ttfb_p50_ms:>8.1f} {s.tbt_mean_ms:>7.1f} "
            f"{s.throughput_tok_s:>10.1f} {s.qps:>7.2f} {s.error_rate*100:>5.1f}"
        )
    return "\n".join(rows)
